"""Melexis AMSKY01 viewer from serial data or HDF5 log replay

Shows:
- IR mapu z MLX90641 ($thrmap)
- Ta/Vdd z MLX90641 ($cloud_meta)
- rohy/střed z MLX90641 ($cloud)
- teplotu a vlhkost ze SHT4x ($hygro)
- osvětlení z TSL2591 ($light) včetně SQM

Závislosti:
    pip install pyserial numpy pyqtgraph PySide6 h5py

Spuštění (příklad):
    python amsky_viewer.py --port /dev/ttyACM0 --baud 115200
    python amsky_viewer.py --port /dev/ttyACM0 --baud 115200 --log --log-name AMSKY01
    python amsky_viewer.py --replay AMSKY01_20260502_18.h5
    python amsky_viewer.py --replay AMSKY01_20260502_18.h5 --replay-speed 5
    python amsky_viewer.py --port /dev/ttyACM0 --headless --log --verbose
"""

import argparse
import os
import sys
import time
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import numpy as np
import serial
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore, QtGui

try:
    import h5py
    HDF5_AVAILABLE = True
except ImportError:
    HDF5_AVAILABLE = False


# AMSKY02B: MLX90642 32x24 (nahrazuje starší MLX90641 16x12 z AMSKY01A/B)
ROWS = 24
COLS = 32
PIXELS = ROWS * COLS

# Korekční parametry
TAU_LENS = 0.90
BETA = 0.2
K_ATM = 0.03


def parse_thrmap(line: str):
    """Parse $thrmap,<sensor_id>,<192 values>"""
    line = line.strip()
    if not line.startswith("$thrmap,"):
        return None

    parts = line.split(",")
    # Očekáváme: $thrmap,1,val1,val2,...,val192 nebo $thrmap,2,...
    if len(parts) < 2 + PIXELS:
        return None

    try:
        sensor_id = int(parts[1])
        values = np.array([float(x) for x in parts[2:2+PIXELS]], dtype=np.float32)
    except (ValueError, IndexError):
        return None

    frame = values.reshape((ROWS, COLS))
    return sensor_id, frame


def parse_hygro(line: str):
    """$hygro,<temp>,<humidity>,<dew_point>"""
    line = line.strip()
    if not line.startswith("$hygro,"):
        return None
    parts = line.split(",")
    if len(parts) < 4:
        return None
    try:
        temp = float(parts[1])
        rh = float(parts[2])
        dew_point = float(parts[3])
    except ValueError:
        return None
    return temp, rh, dew_point


def parse_light(line: str):
    """$light,<channel>,normalized_lux,full_raw,ir_raw,gain,integration_time,sqm

    AMSKY02B čte TSL2591 na obou kanálech I2C muxu, proto zpráva nově
    obsahuje číslo kanálu (0 nebo 1) jako první pole.
    """
    line = line.strip()
    if not line.startswith("$light,"):
        return None
    parts = line.split(",")
    if len(parts) < 8:
        return None
    try:
        channel = int(parts[1])
        lux = float(parts[2])
        full_raw = float(parts[3])
        ir_raw = float(parts[4])
        gain = parts[5]
        itime = parts[6]
        sqm = float(parts[7])
    except ValueError:
        return None
    return channel, lux, full_raw, ir_raw, gain, itime, sqm


def parse_cloud_meta(line: str):
    """$cloud_meta,<sensor_id>,<vdd>,<ta>"""
    line = line.strip()
    if not line.startswith("$cloud_meta,"):
        return None
    parts = line.split(",")
    if len(parts) < 4:
        return None
    try:
        sensor_id = int(parts[1])
        vdd = float(parts[2])
        ta = float(parts[3])
    except ValueError:
        return None
    return sensor_id, vdd, ta


def parse_cloud(line: str):
    """$cloud,<sensor_id>,TL,TR,BL,BR,CENTER"""
    line = line.strip()
    if not line.startswith("$cloud,"):
        return None
    parts = line.split(",")
    if len(parts) < 7:
        return None
    try:
        sensor_id = int(parts[1])
        tl = float(parts[2])
        tr = float(parts[3])
        bl = float(parts[4])
        br = float(parts[5])
        center = float(parts[6])
    except ValueError:
        return None
    return sensor_id, tl, tr, bl, br, center


def dewpoint_magnus(Ta_C: float, RH_pct: float) -> float:
    """Výpočet rosného bodu pomocí Magnusovy rovnice."""
    a = 17.27
    b = 237.7
    alpha = ((a * Ta_C) / (b + Ta_C)) + np.log(RH_pct / 100.0)
    Td_C = (b * alpha) / (a - alpha)
    return Td_C


def apply_sky_temperature_correction(T_meas_C: np.ndarray, Ta_C: float, RH_pct: float, 
                                     Tchip_C: float, tau_lens: float = TAU_LENS, 
                                     beta: float = BETA, k_atm: float = K_ATM) -> np.ndarray:
    """
    Aplikuje atmosférickou a optickou korekci na měřené teploty.
    
    Args:
        T_meas_C: Měřené teploty v °C (2D pole)
        Ta_C: Teplota vzduchu v °C
        RH_pct: Relativní vlhkost v %
        Tchip_C: Teplota čipu (MLX Ta) v °C
        tau_lens: Transmisivita čočky (default 0.90)
        beta: Korekční faktor pro teplotu čočky (default 0.2)
        k_atm: Atmosférický koeficient (default 0.03)
    
    Returns:
        T_sky_corr_C: Korigované teploty v °C (2D pole)
    """
    # Výpočet rosného bodu
    Td_C = dewpoint_magnus(Ta_C, RH_pct)
    
    # Výpočet W s omezením na rozsah 0-30
    W = np.clip(Ta_C - Td_C, 0, 30)
    
    # Atmosférická transmisivita
    tau_atm = np.exp(-k_atm * (30 - W))
    
    # Teplota čočky
    T_lens_C = Ta_C + beta * (Tchip_C - Ta_C)
    
    # Stefanovy-Boltzmannovy radiace
    R_atm = (Ta_C + 273.15) ** 4
    R_lens = (T_lens_C + 273.15) ** 4
    
    # Korekce pro každý pixel
    R_meas = (T_meas_C + 273.15) ** 4
    R_sky = (R_meas - tau_lens * (1 - tau_atm) * R_atm - (1 - tau_lens) * R_lens) / (tau_lens * tau_atm)
    
    # Převod zpět na teplotu
    T_sky_corr_C = np.power(R_sky, 0.25) - 273.15
    
    return T_sky_corr_C


def calculate_tsl2591_lux(ch0_full, ch1_ir, gain_str, integration_time_str):
    """
    Vypočítá lux hodnotu z TSL2591 raw dat
    
    FW to počítá, zde se to počítá nezávisle.. 
   
    Args:
        ch0_full: Raw hodnota z kanálu 0 (IR + Visible, 16-bit)
        ch1_ir: Raw hodnota z kanálu 1 (pouze IR, 16-bit)
        gain_str: Řetězec reprezentující gain ("1x", "25x", "428x", "9876x")
        integration_time_str: Řetězec reprezentující integrační čas ("100ms", "200ms", atd.)
    
    Returns:
        float: Vypočtená lux hodnota, nebo -1 při přetečení
    """
    # Kontrola přetečení
    if ch0_full == 0xFFFF or ch1_ir == 0xFFFF:
        return -1.0
    
    # Mapování integration time string na ms hodnotu
    # Firmware posílá integration time jako "100", "200", atd. (bez "ms")
    integration_time_map = {
        "100": 100.0,
        "200": 200.0,
        "300": 300.0,
        "400": 400.0,
        "500": 500.0,
        "600": 600.0,
        # Podpora i s "ms" pro zpětnou kompatibilitu
        "100ms": 100.0,
        "200ms": 200.0,
        "300ms": 300.0,
        "400ms": 400.0,
        "500ms": 500.0,
        "600ms": 600.0,
    }
    atime = integration_time_map.get(integration_time_str, 100.0)
    
    # Mapování gain string na numerickou hodnotu
    # Firmware posílá gain jako "1", "25", "428", "9876" (bez "x")
    gain_map = {
        "1": 1.0,         # LOW gain
        "25": 25.0,       # MED gain
        "428": 428.0,     # HIGH gain
        "9876": 9876.0,   # MAX gain
        # Podpora i s "x" pro zpětnou kompatibilitu
        "1x": 1.0,
        "25x": 25.0,
        "428x": 428.0,
        "9876x": 9876.0,
    }
    again = gain_map.get(gain_str, 1.0)
    
    # TSL2591 konstanty z Adafruit knihovny
    TSL2591_LUX_DF = 408.0
    
    # Výpočet counts per lux (CPL)
    cpl = (atime * again) / TSL2591_LUX_DF
    
    # Alternativní lux výpočet #1 (používaný v aktuální knihovně)
    # Tento algoritmus používá dynamický koeficient založený na poměru IR/Full
    # Reference: https://github.com/adafruit/Adafruit_TSL2591_Library/issues/14
    if ch0_full > 0:
        lux = ((float(ch0_full) - float(ch1_ir)) * (1.0 - (float(ch1_ir) / float(ch0_full)))) / cpl
    else:
        lux = 0.0
    
    return lux




def gain_str_to_float(gain_str: str) -> float:
    """Převede gain string na numerickou hodnotu."""
    gain_map = {
        "1": 1.0,
        "25": 25.0,
        "428": 428.0,
        "9876": 9876.0,
        "1x": 1.0,
        "25x": 25.0,
        "428x": 428.0,
        "9876x": 9876.0,
    }
    return gain_map.get(gain_str, 1.0)

def calculate_sqm_from_raw(ir_raw, full_raw, gain_value, integration_ms, 
                           sqm_offset_base=12.6, sqm_magnitude_const=1.086, 
                           calibration_offset=0.0):
    """
    Vypočítá SQM (Sky Brightness) z raw TSL2591 senzorových dat.
    
    Algoritmus podle specifikace:
    1) Změř raw hodnoty kanálů (ir_raw = CH1, full_raw = CH0)
    2) Volitelná teplotní korekce (zakomentována)
    3) Viditelná složka (vis_raw = full_raw - ir_raw)
    4) Normalizace na referenci 200ms a na gain
    5) Převod na mag/arcsec^2 pomocí ln()
    6) Odhad chyby
    
    Args:
        ir_raw: Raw IR hodnota (CH1)
        full_raw: Raw FULL hodnota (CH0 = VIS + IR)
        gain_value: Aktuální zesílení senzoru
        integration_ms: Integrační čas v milisekundách
        sqm_offset_base: Základní konstanta pro výpočet (typicky 12.6)
        sqm_magnitude_const: Konstanta pro ln() konverzi (typicky 1.086)
        calibration_offset: Kalibrační offset (může být 0.0)
    
    Returns:
        dict s klíči:
            - 'valid': bool, zda je měření validní
            - 'mpsas': float, jas oblohy v mag/arcsec^2
            - 'dmpsas': float, odhad chyby
    """
    import math
    
    result = {'valid': False, 'mpsas': None, 'dmpsas': None}
    
    # 1) Raw hodnoty jsou již naměřeny (parametry)
    # ir_raw = CH1 (IR)
    # full_raw = CH0 (FULL = VIS + IR)
    
    # 2) Teplotní korekce - ZAKOMENTOVÁNA
    # if temperature_available:
    #     ir_raw = ir_raw * (temperature * ir_slope + ir_intercept)
    #     full_raw = full_raw * (temperature * full_slope + full_intercept)
    
    # 3) Viditelná složka
    vis_raw = float(full_raw) - float(ir_raw)
    if vis_raw <= 0.0:
        # Invalidní měření - nižší viditelná složka
        return result
    
    # 4) Normalizace na referenci 200 ms a na gain
    # normalization = gainValue * (integrationMs / 200.0) * niter
    normalization = gain_value * (integration_ms / 200.0) * 1
    vis = vis_raw / normalization
    
    if vis <= 0.0:
        # Invalidní měření - normalizovaná viditelná složka je nula nebo negativní
        return result
    
    # 5) Převod na mag/arcsec^2
    # mpsas = sqmOffsetBase - sqmMagnitude * ln(VIS) + calibrationOffset
    # (ln je přirozený logaritmus)
    mpsas = sqm_offset_base - sqm_magnitude_const * math.log(vis) + calibration_offset
    
    # 6) Odhad chyby (podle knihovny; bere sqrt z nenormalizovaného vis_raw)
    # dmpsas = sqmMagnitude / sqrt(vis_raw)
    dmpsas = sqm_magnitude_const / math.sqrt(vis_raw)
    
    result['valid'] = True
    result['mpsas'] = mpsas
    result['dmpsas'] = dmpsas
    
    return result


def calculate_sqm(full_raw: int, ir_raw: int, itime_ms: float, gain: float, 
                  sqm_offset_base: float = 12.6, sqm_magnitude_const: float = 1.086,
                  zp: float = None) -> float:
    """
    Převod TSL2591 raw dat -> sky brightness (mag/arcsec^2) pomocí nového algoritmu.
    
    Tato funkce je kompatibilní se starým rozhraním, ale používá nový algoritmus.
    
    Args:
        full_raw: Raw FULL hodnota (CH0)
        ir_raw: Raw IR hodnota (CH1)
        itime_ms: Integrační čas v milisekundách
        gain: Aktuální zesílení senzoru
        sqm_offset_base: Základní konstanta (default 12.6)
        sqm_magnitude_const: Konstanta pro ln() (default 1.086)
        zp: Zastaralá kalibrační konstanta (ignorována, pro backward compatibility)
    
    Returns:
        float: SQM v mag/arcsec^2, nebo float('inf') pokud je měření invalidní
    """
    result = calculate_sqm_from_raw(ir_raw, full_raw, gain, itime_ms,
                                    sqm_offset_base, sqm_magnitude_const, 0.0)
    
    if result['valid']:
        return result['mpsas']
    else:
        return float('inf')

def calculate_normalized_lux(ch0_full, ch1_ir, gain_str, integration_time_str):
    """
    Vypočítá normalizovanou lux hodnotu (jako ve firmware AMSKY01).
    
    Normalizace odstraňuje závislost na aktuálním nastavení gain a integration time,
    čímž poskytuje konzistentní hodnotu nezávislou na nastavení senzoru.
    
    Poznámka: Firmware na AMSKY01 toto už počítá a posílá jako normalized_lux v $light zprávě.
    Tato funkce je zde pro nezávislé ověření nebo pro případy, kdy máme pouze raw data.
    
    Args:
        ch0_full: Raw hodnota z kanálu 0 (IR + Visible, 16-bit)
        ch1_ir: Raw hodnota z kanálu 1 (pouze IR, 16-bit)
        gain_str: Řetězec reprezentující gain
        integration_time_str: Řetězec reprezentující integrační čas
    
    Returns:
        float: Normalizovaná lux hodnota
    """
    # Nejprve vypočti základní lux
    lux = calculate_tsl2591_lux(ch0_full, ch1_ir, gain_str, integration_time_str)
    
    if lux < 0:
        return lux
    
    # Mapování pro normalizaci
    gain_map = {"1": 1.0, "25": 25.0, "428": 428.0, "9876": 9876.0, "1x": 1.0, "25x": 25.0, "428x": 428.0, "9876x": 9876.0}
    integration_time_map = {
        "100": 100.0, "200": 200.0, "300": 300.0,
        "400": 400.0, "500": 500.0, "600": 600.0,
        "100ms": 100.0, "200ms": 200.0, "300ms": 300.0,
        "400ms": 400.0, "500ms": 500.0, "600ms": 600.0,
    }
    
    gain_val = gain_map.get(gain_str, 1.0)
    itime_val = integration_time_map.get(integration_time_str, 100.0)
    
    # Normalizační faktor (300ms je referenční integration time)
    normalization_factor = gain_val * itime_val / 300.0
    normalized_lux = lux / normalization_factor
    
    return normalized_lux



class HDF5Logger:
    """Třída pro logování dat do HDF5 souborů (hodinové dávky)."""

    def __init__(self, device_id: str, base_path: Path = None):
        self.device_id = device_id
        self.base_path = base_path or Path(".")
        self.base_path.mkdir(parents=True, exist_ok=True)

        self.current_file = None
        self.current_hour = None

        # Datasety – oba senzory ukládány odděleně jako /sky1 a /sky2
        self.sky1_data = None
        self.sky1_time = None
        self.sky1_temp = None
        self.sky2_data = None
        self.sky2_time = None
        self.sky2_temp = None

        self.hygro_temp = None
        self.hygro_hum = None
        self.hygro_time = None

        # /light0 a /light1 — TSL2591 na obou kanálech I2C muxu, odděleně
        for ch in (0, 1):
            for name in ("all", "ir", "gain", "expo", "time"):
                setattr(self, f"light{ch}_{name}", None)

        # /cloud{1,2}/ — rohy + střed + Vdd
        for sid in (1, 2):
            for name in ("tl", "tr", "bl", "br", "center", "vdd", "time"):
                setattr(self, f"cloud{sid}_{name}", None)
    
    def _get_current_hour(self):
        """Vrací aktuální hodinu jako datetime objekt (UTC)."""
        now = datetime.now(timezone.utc)
        return now.replace(minute=0, second=0, microsecond=0)
    
    def _get_filename(self, dt: datetime) -> str:
        """Generuje název souboru podle specifikace."""
        return f"{self.device_id}_{dt.strftime('%Y%m%d_%H')}.h5"
    
    def _ensure_file(self):
        """Zajistí, že je otevřený správný HDF5 soubor pro aktuální hodinu."""
        current_hour = self._get_current_hour()
        
        if self.current_hour != current_hour:
            # Zavřít starý soubor
            if self.current_file is not None:
                self.current_file.close()
                print(f"HDF5: uzavřen soubor pro hodinu {self.current_hour}")
            
            # Otevřít nový soubor
            self.current_hour = current_hour
            filename = self._get_filename(current_hour)
            filepath = self.base_path / filename
            
            self.current_file = h5py.File(filepath, "a")
            print(f"HDF5: otevřen soubor {filepath}")
            
            # Vytvořit/otevřít skupiny a datasety
            self._init_datasets()
    
    def _init_datasets(self):
        """Inicializuje nebo otevře datasety v aktuálním souboru."""
        f = self.current_file

        # Skupiny /sky1 a /sky2 (každý senzor zvlášť)
        for sid in (1, 2):
            gname = f"sky{sid}"
            if gname not in f:
                grp = f.create_group(gname)
                setattr(self, f"sky{sid}_data", grp.create_dataset(
                    "data", shape=(0, ROWS, COLS), maxshape=(None, ROWS, COLS),
                    dtype=np.float32, chunks=(1, ROWS, COLS)
                ))
                setattr(self, f"sky{sid}_time", grp.create_dataset(
                    "time", shape=(0,), maxshape=(None,), dtype=np.int64, chunks=(1024,)
                ))
                setattr(self, f"sky{sid}_temp", grp.create_dataset(
                    "temp", shape=(0,), maxshape=(None,), dtype=np.float32, chunks=(1024,)
                ))
            else:
                grp = f[gname]
                setattr(self, f"sky{sid}_data", grp["data"])
                setattr(self, f"sky{sid}_time", grp["time"])
                setattr(self, f"sky{sid}_temp", grp["temp"])
        
        # Skupina /hygro
        if "hygro" not in f:
            hygro_grp = f.create_group("hygro")
            self.hygro_temp = hygro_grp.create_dataset(
                "temp", shape=(0,), maxshape=(None,),
                dtype=np.float32, chunks=(1024,)
            )
            self.hygro_hum = hygro_grp.create_dataset(
                "hum", shape=(0,), maxshape=(None,),
                dtype=np.float32, chunks=(1024,)
            )
            self.hygro_time = hygro_grp.create_dataset(
                "time", shape=(0,), maxshape=(None,),
                dtype=np.int64, chunks=(1024,)
            )
        else:
            hygro_grp = f["hygro"]
            self.hygro_temp = hygro_grp["temp"]
            self.hygro_hum = hygro_grp["hum"]
            self.hygro_time = hygro_grp["time"]
        
        # Skupiny /light0 a /light1 — TSL2591 na obou kanálech I2C muxu
        for ch in (0, 1):
            gname = f"light{ch}"
            if gname not in f:
                light_grp = f.create_group(gname)
                setattr(self, f"light{ch}_all", light_grp.create_dataset(
                    "all", shape=(0,), maxshape=(None,),
                    dtype=np.float32, chunks=(1024,)
                ))
                setattr(self, f"light{ch}_ir", light_grp.create_dataset(
                    "ir", shape=(0,), maxshape=(None,),
                    dtype=np.float32, chunks=(1024,)
                ))
                setattr(self, f"light{ch}_gain", light_grp.create_dataset(
                    "gain", shape=(0,), maxshape=(None,),
                    dtype=np.float32, chunks=(1024,)
                ))
                setattr(self, f"light{ch}_expo", light_grp.create_dataset(
                    "expo", shape=(0,), maxshape=(None,),
                    dtype=np.float32, chunks=(1024,)
                ))
                setattr(self, f"light{ch}_time", light_grp.create_dataset(
                    "time", shape=(0,), maxshape=(None,),
                    dtype=np.int64, chunks=(1024,)
                ))
            else:
                light_grp = f[gname]
                setattr(self, f"light{ch}_all", light_grp["all"])
                setattr(self, f"light{ch}_ir", light_grp["ir"])
                setattr(self, f"light{ch}_gain", light_grp["gain"])
                setattr(self, f"light{ch}_expo", light_grp["expo"])
                setattr(self, f"light{ch}_time", light_grp["time"])

        # Skupiny /cloud1 a /cloud2 — rohy, střed a Vdd
        for sid in (1, 2):
            gname = f"cloud{sid}"
            if gname not in f:
                grp = f.create_group(gname)
                for name in ("tl", "tr", "bl", "br", "center", "vdd"):
                    setattr(self, f"cloud{sid}_{name}", grp.create_dataset(
                        name, shape=(0,), maxshape=(None,),
                        dtype=np.float32, chunks=(1024,)
                    ))
                setattr(self, f"cloud{sid}_time", grp.create_dataset(
                    "time", shape=(0,), maxshape=(None,),
                    dtype=np.int64, chunks=(1024,)
                ))
            else:
                grp = f[gname]
                for name in ("tl", "tr", "bl", "br", "center", "vdd", "time"):
                    setattr(self, f"cloud{sid}_{name}", grp[name])

    def _get_timestamp_ns(self) -> int:
        """Vrací aktuální Unix timestamp v nanosekundách."""
        return int(time.time() * 1e9)
    
    def log_sky(self, sensor_id: int, frame: np.ndarray, temp: float):
        """Zaloguje IR snímek do /sky1 nebo /sky2."""
        self._ensure_file()

        timestamp = self._get_timestamp_ns()
        data_ds = getattr(self, f"sky{sensor_id}_data")
        time_ds = getattr(self, f"sky{sensor_id}_time")
        temp_ds = getattr(self, f"sky{sensor_id}_temp")

        n = data_ds.shape[0]
        data_ds.resize((n + 1, ROWS, COLS))
        time_ds.resize((n + 1,))
        temp_ds.resize((n + 1,))

        data_ds[n] = frame
        time_ds[n] = timestamp
        temp_ds[n] = temp

        self.current_file.flush()
    
    def log_hygro(self, temp: float, hum: float):
        """Zaloguje data ze SHT4x do /hygro."""
        self._ensure_file()
        
        timestamp = self._get_timestamp_ns()
        
        n = self.hygro_temp.shape[0]
        self.hygro_temp.resize((n + 1,))
        self.hygro_hum.resize((n + 1,))
        self.hygro_time.resize((n + 1,))
        
        self.hygro_temp[n] = temp
        self.hygro_hum[n] = hum
        self.hygro_time[n] = timestamp
        
        self.current_file.flush()
    
    def log_light(self, channel: int, full: float, ir: float, gain: float, expo: float):
        """Zaloguje data z TSL2591 daného kanálu muxu (0/1) do /light{channel}."""
        self._ensure_file()

        timestamp = self._get_timestamp_ns()

        all_ds = getattr(self, f"light{channel}_all")
        ir_ds = getattr(self, f"light{channel}_ir")
        gain_ds = getattr(self, f"light{channel}_gain")
        expo_ds = getattr(self, f"light{channel}_expo")
        time_ds = getattr(self, f"light{channel}_time")

        n = all_ds.shape[0]
        all_ds.resize((n + 1,))
        ir_ds.resize((n + 1,))
        gain_ds.resize((n + 1,))
        expo_ds.resize((n + 1,))
        time_ds.resize((n + 1,))

        all_ds[n] = full
        ir_ds[n] = ir
        gain_ds[n] = gain
        expo_ds[n] = expo
        time_ds[n] = timestamp

        self.current_file.flush()
    
    def log_cloud(self, sensor_id: int, tl: float, tr: float, bl: float,
                  br: float, center: float, vdd: float = float('nan')):
        """Zaloguje rohy/střed/Vdd pro daný senzor (1 nebo 2) do /cloud{N}."""
        self._ensure_file()

        timestamp = self._get_timestamp_ns()
        values = {"tl": tl, "tr": tr, "bl": bl, "br": br,
                  "center": center, "vdd": vdd}

        time_ds = getattr(self, f"cloud{sensor_id}_time")
        n = time_ds.shape[0]
        time_ds.resize((n + 1,))
        time_ds[n] = timestamp

        for name, value in values.items():
            ds = getattr(self, f"cloud{sensor_id}_{name}")
            ds.resize((n + 1,))
            ds[n] = value

        self.current_file.flush()

    def close(self):
        """Zavře aktuální HDF5 soubor."""
        if self.current_file is not None:
            self.current_file.close()
            self.current_file = None


class DataHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler pro poskytování dat přes JSON API."""
    
    data_source = None  # Bude nastaveno z hlavního okna
    
    def do_GET(self):
        if self.path == "/data.json":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            if self.data_source:
                data = self.data_source.get_json_data()
                self.wfile.write(json.dumps(data, indent=2).encode())
            else:
                self.wfile.write(b'{"error": "no data"}')
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Potlač log zprávy
        pass


class HeadlessRunner:
    """Headless (no-GUI) běh nad seriovou linkou.

    Parsuje příchozí $thrmap / $hygro / $light / $cloud_meta / $cloud, loguje
    do HDF5 (pokud zapnuto) a volitelně vypisuje hodnoty na stdout.
    """

    def __init__(self, ser, device_id="AMSKY01", log_path=".",
                 enable_logging=True, verbose=False, sqm_zp=24.0,
                 stats_interval=10.0):
        self.ser = ser
        self.verbose = verbose
        self.sqm_zp = sqm_zp
        self.stats_interval = stats_interval

        self.line_buffer = ""
        self.logger = None
        if enable_logging:
            if not HDF5_AVAILABLE:
                print("VAROVÁNÍ: h5py není dostupné, logování vypnuto", file=sys.stderr)
            else:
                self.logger = HDF5Logger(device_id, Path(log_path or "."))
                print(f"HDF5 logování aktivní: {device_id} -> {log_path or '.'}")

        # Poslední známé hodnoty pro logování
        self.last_ta = {1: None, 2: None}
        self.last_vdd = {1: float('nan'), 2: float('nan')}

        # Počítadla pro periodický status
        self.counters = {"thrmap1": 0, "thrmap2": 0, "hygro": 0,
                         "light0": 0, "light1": 0, "cloud1": 0, "cloud2": 0,
                         "cloud_meta1": 0, "cloud_meta2": 0}
        self._stats_last = time.time()
        self._running = True

    def _vlog(self, msg: str):
        if self.verbose:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] {msg}", flush=True)

    def _print_stats(self):
        now = time.time()
        if now - self._stats_last < self.stats_interval:
            return
        dt = now - self._stats_last
        parts = [f"{k}={v}" for k, v in self.counters.items() if v > 0]
        log_state = ""
        if self.logger and self.logger.current_file:
            log_state = f" log={self.logger._get_filename(self.logger.current_hour)}"
        print(f"[stats {dt:.1f}s] " + ", ".join(parts) + log_state, flush=True)
        for k in self.counters:
            self.counters[k] = 0
        self._stats_last = now

    def process_line(self, line: str):
        s = line.strip()
        if not s:
            return

        if s.startswith("$thrmap,"):
            result = parse_thrmap(s)
            if result is None:
                return
            sensor_id, frame = result
            self.counters[f"thrmap{sensor_id}"] += 1
            self._vlog(f"thrmap S{sensor_id}: min={frame.min():.2f} "
                       f"max={frame.max():.2f} mean={frame.mean():.2f} °C")
            if self.logger and self.last_ta[sensor_id] is not None:
                self.logger.log_sky(sensor_id, frame, self.last_ta[sensor_id])
            return

        if s.startswith("$hygro,"):
            v = parse_hygro(s)
            if v is None:
                return
            t, rh, dew = v
            self.counters["hygro"] += 1
            self._vlog(f"hygro: T={t:.2f}°C RH={rh:.2f}% dew={dew:.2f}°C")
            if self.logger:
                self.logger.log_hygro(t, rh)
            return

        if s.startswith("$light,"):
            v = parse_light(s)
            if v is None:
                return
            channel, lux, full_raw, ir_raw, gain, itime, sqm_fw = v
            self.counters[f"light{channel}"] += 1
            try:
                gain_val = gain_str_to_float(gain)
                itime_val = float(str(itime).rstrip('ms'))
                sqm_calc = calculate_sqm(int(full_raw), int(ir_raw),
                                         itime_val, gain_val, self.sqm_zp)
                sqm_str = f"{sqm_calc:.2f}" if sqm_calc != float('inf') else "inf"
            except Exception:
                gain_val, itime_val, sqm_str = 1.0, 100.0, "n/a"
            self._vlog(f"light ch{channel}: full={full_raw:.0f} ir={ir_raw:.0f} "
                       f"gain={gain} int={itime} lux={lux:.4f} sqm={sqm_str}")
            if self.logger:
                try:
                    self.logger.log_light(channel, full_raw, ir_raw, gain_val, itime_val)
                except Exception as e:
                    print(f"chyba logování light: {e}", file=sys.stderr)
            return

        if s.startswith("$cloud_meta,"):
            v = parse_cloud_meta(s)
            if v is None:
                return
            sensor_id, vdd, ta = v
            self.counters[f"cloud_meta{sensor_id}"] += 1
            self.last_ta[sensor_id] = ta
            self.last_vdd[sensor_id] = vdd
            self._vlog(f"cloud_meta S{sensor_id}: Vdd={vdd:.3f} V Ta={ta:.3f} °C")
            return

        if s.startswith("$cloud,"):
            v = parse_cloud(s)
            if v is None:
                return
            sensor_id, tl, tr, bl, br, ctr = v
            self.counters[f"cloud{sensor_id}"] += 1
            self._vlog(f"cloud S{sensor_id}: TL={tl:.2f} TR={tr:.2f} "
                       f"BL={bl:.2f} BR={br:.2f} C={ctr:.2f} °C")
            if self.logger:
                self.logger.log_cloud(sensor_id, tl, tr, bl, br, ctr,
                                      self.last_vdd[sensor_id])
            return

    def run(self):
        """Hlavní smyčka — čte ze seriové linky a zpracovává řádky."""
        if self.ser is None:
            print("Chyba: headless režim vyžaduje --port", file=sys.stderr)
            return 1

        print(f"Headless mode: čtu z {self.ser.port} @ {self.ser.baudrate} Bd",
              flush=True)
        try:
            while self._running:
                try:
                    waiting = self.ser.in_waiting
                    if waiting:
                        chunk = self.ser.read(waiting).decode(errors="ignore")
                        self.line_buffer += chunk
                        while "\n" in self.line_buffer:
                            line, self.line_buffer = self.line_buffer.split("\n", 1)
                            self.process_line(line)
                    else:
                        time.sleep(0.02)
                except serial.SerialException as e:
                    print(f"Serial error: {e}", file=sys.stderr)
                    return 2
                self._print_stats()
        except KeyboardInterrupt:
            print("\nUkončeno uživatelem (Ctrl+C)")
        finally:
            if self.logger:
                self.logger.close()
        return 0


class ConfigDialog(QtWidgets.QDialog):
    """Konfigurační dialog."""
    
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Configuration")
        
        layout = QtWidgets.QFormLayout(self)
        
        # HTTP port
        self.http_port_spin = QtWidgets.QSpinBox()
        self.http_port_spin.setRange(1024, 65535)
        self.http_port_spin.setValue(settings.value("http_port", 8080, type=int))
        layout.addRow("HTTP Port:", self.http_port_spin)
        
        # Log path
        self.log_path_edit = QtWidgets.QLineEdit()
        self.log_path_edit.setText(settings.value("log_path", "."))
        browse_btn = QtWidgets.QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_log_path)
        path_layout = QtWidgets.QHBoxLayout()
        path_layout.addWidget(self.log_path_edit)
        path_layout.addWidget(browse_btn)
        layout.addRow("Log Path:", path_layout)
        
        # Log name
        self.log_name_edit = QtWidgets.QLineEdit()
        self.log_name_edit.setText(settings.value("log_name", "AMSKY01"))
        layout.addRow("Log Name:", self.log_name_edit)
        
        # Buttons
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
    
    def browse_log_path(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Log Directory")
        if path:
            self.log_path_edit.setText(path)
    
    def accept(self):
        self.settings.setValue("http_port", self.http_port_spin.value())
        self.settings.setValue("log_path", self.log_path_edit.text())
        self.settings.setValue("log_name", self.log_name_edit.text())
        super().accept()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, ser=None, vmin=None, vmax=None, rotation=0.0, debug=False,
                 enable_logging=False, enable_http_api=False, device_id="AMSKY01", log_path=None, sqm_zp=24.0,
                 replay_file=None, replay_speed=1.0, parent=None):
        super().__init__(parent)
        self.ser = ser
        self.vmin = vmin
        self.vmax = vmax
        self.rotation = rotation
        self.debug = debug
        self.sqm_zp = sqm_zp
        self.line_buffer = ""
        self.levels_initialized = False

        # Replay mode
        self.replay_file = replay_file
        self.replay_speed = replay_speed
        self.replay_data = None
        self.replay_frame_idx = 0
        self.replay_playing = False
        self.replay_start_real = None
        self.replay_start_data_ns = None
        
        # Settings
        self.settings = QtCore.QSettings("AstroMeters", "AMSKY01Viewer")
        
        # HDF5 logování
        self.logging_enabled = enable_logging and HDF5_AVAILABLE
        self.device_id = device_id or self.settings.value("log_name", "AMSKY01")
        self.logger = None
        
        if self.logging_enabled:
            log_path = log_path or self.settings.value("log_path", ".")
            self.logger = HDF5Logger(self.device_id, Path(log_path))
            print(f"HDF5 logování aktivní: {self.device_id}")
        elif enable_logging and not HDF5_AVAILABLE:
            print("VAROVÁNÍ: h5py není dostupné, logování vypnuto")
        
        # Pro logování sky dat potřebujeme poslední známou Ta
        self.last_ta1 = None
        self.last_ta2 = None
        # Poslední známá Vdd z $cloud_meta — připojí se k $cloud zápisu
        self.last_vdd1 = float('nan')
        self.last_vdd2 = float('nan')
        
        # Režim zobrazení (raw vs calibrated)
        self.show_calibrated = False
        
        # Poslední známé hodnoty pro korekci
        self.last_ambient_temp = 20.0  # Ta
        self.last_humidity = 50.0       # RH
        
        # Aktuální data pro JSON API
        self.current_data = {
            "timestamp": None,
            "hygro": {"temp": None, "rh": None, "dew_point": None},
            "light0": {"lux": None, "full": None, "ir": None, "gain": None, "itime": None, "sqm": None},
            "light1": {"lux": None, "full": None, "ir": None, "gain": None, "itime": None, "sqm": None},
            "mlx1": {"vdd": None, "ta": None},
            "mlx2": {"vdd": None, "ta": None},
            "cloud1": {"tl": None, "tr": None, "bl": None, "br": None, "center": None},
            "cloud2": {"tl": None, "tr": None, "bl": None, "br": None, "center": None},
            "thrmap1": None,
            "thrmap2": None
        }
        
        # HTTP server
        self.http_server = None
        self.http_thread = None
        self.http_enabled = False
        self.enable_http_api_on_start = enable_http_api

        self.setWindowTitle("AMSKY01 viewer")
        
        # --- Menu bar ---
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        
        open_replay_action = QtGui.QAction("&Open Replay File...", self)
        open_replay_action.setShortcut("Ctrl+O")
        open_replay_action.triggered.connect(self._open_replay_file_dialog)
        open_replay_action.setEnabled(HDF5_AVAILABLE)
        file_menu.addAction(open_replay_action)

        file_menu.addSeparator()

        self.log_action = QtGui.QAction("Start &Logging", self, checkable=True)
        self.log_action.setChecked(self.logging_enabled)
        self.log_action.setEnabled(HDF5_AVAILABLE)
        self.log_action.triggered.connect(self.toggle_logging)
        file_menu.addAction(self.log_action)

        file_menu.addSeparator()

        config_action = QtGui.QAction("&Configuration...", self)
        config_action.triggered.connect(self.show_config)
        file_menu.addAction(config_action)
        
        file_menu.addSeparator()
        
        exit_action = QtGui.QAction("E&xit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # View menu
        view_menu = menubar.addMenu("&View")
        
        self.calibrated_action = QtGui.QAction("Show &Calibrated Temperature", self, checkable=True)
        self.calibrated_action.setChecked(self.show_calibrated)
        self.calibrated_action.triggered.connect(self.toggle_calibrated)
        view_menu.addAction(self.calibrated_action)

        # --- Central widget s tab widgetem ---
        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)
        
        # Tab 1: Graf
        self.create_graph_tab()
        
        # Tab 2: Tabulka dat
        self.create_table_tab()
        
        # Tab 3: HTTP API
        self.create_api_tab()
        
        # Status bar
        self.statusBar().showMessage("Not logging")

        # Timer na polling seriáku / replay
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(50)  # ms
        self.timer.timeout.connect(self._on_poll_timer)
        self.timer.start()

        # Načti replay soubor pokud byl zadán při startu
        if self.replay_file and HDF5_AVAILABLE:
            QtCore.QTimer.singleShot(100, lambda: self._load_replay_data(self.replay_file))

        # Start HTTP API if requested
        if self.enable_http_api_on_start:
            self.api_enable_check.setChecked(True)
            self.toggle_http_api(True)
    
    def create_graph_tab(self):
        """Vytvoří první kartu s grafem."""
        graph_widget = QtWidgets.QWidget()
        main_vbox = QtWidgets.QVBoxLayout(graph_widget)
        main_vbox.setContentsMargins(0, 0, 0, 0)
        main_vbox.setSpacing(0)

        content_widget = QtWidgets.QWidget()
        hbox = QtWidgets.QHBoxLayout(content_widget)
        main_vbox.addWidget(content_widget, 1)

        # Levá část: Jeden IR obraz (kombinovaná matice)
        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.setBackground("#1a1a1a")
        hbox.addWidget(self.graphics, 2)

        # Jeden kombinovaný obraz
        self.view = self.graphics.addViewBox()
        self.view.setAspectLocked(True)
        self.img_item = pg.ImageItem()
        self.view.addItem(self.img_item)
        
        # Text label pro zobrazení hodnoty pod kurzorem
        self.value_label = pg.TextItem(anchor=(0, 1), color='w', fill=(0, 0, 0, 150))
        self.view.addItem(self.value_label)
        self.value_label.setPos(0, 0)
        
        # Připojení signálu pro pohyb myši
        self.img_item.hoverEvent = self.image_hover_event

        self.hist_lut = pg.HistogramLUTItem()
        self.graphics.addItem(self.hist_lut)
        self.hist_lut.setImageItem(self.img_item)
        try:
            self.hist_lut.gradient.loadPreset("inferno")
        except Exception:
            pass

        # Data pro oba senzory - po otočení bude každý (12,16) -> (16,12)
        # Spojíme je vedle sebe: (16,24)
        self.img_data1 = np.full((ROWS, COLS), np.nan, dtype=np.float32)
        self.img_data2 = np.full((ROWS, COLS), np.nan, dtype=np.float32)
        self.sensor1_ready = False
        self.sensor2_ready = False
        self.combined_data = np.full((COLS, ROWS * 2), np.nan, dtype=np.float32)
        self._update_combined_image()

        # Pravá část: textové hodnoty
        right_panel = QtWidgets.QWidget()
        hbox.addWidget(right_panel, 1)
        
        right_vbox = QtWidgets.QVBoxLayout(right_panel)
        
        # Status logování
        self.lbl_log_status = QtWidgets.QLabel()
        self.lbl_log_status.setStyleSheet("font-weight: bold; padding: 5px;")
        self._update_log_status()
        right_vbox.addWidget(self.lbl_log_status)
        
        form = QtWidgets.QFormLayout()
        right_vbox.addLayout(form)
        right_vbox.addStretch()

        def make_label():
            lbl = QtWidgets.QLabel("—")
            lbl.setMinimumWidth(120)
            return lbl

        # Hygro
        self.lbl_temp = make_label()
        self.lbl_rh = make_label()
        self.lbl_dew = make_label()
        form.addRow("SHT4x T [°C]", self.lbl_temp)
        form.addRow("SHT4x RH [%]", self.lbl_rh)
        form.addRow("Dew Point [°C]", self.lbl_dew)

        # Light - kanál 0 (mux)
        self.lbl_lux0 = make_label()
        self.lbl_full0 = make_label()
        self.lbl_ir0 = make_label()
        self.lbl_gain0 = make_label()
        self.lbl_itime0 = make_label()
        self.lbl_sqm0 = make_label()
        form.addRow("LIGHT0 Lux", self.lbl_lux0)
        form.addRow("LIGHT0 Full", self.lbl_full0)
        form.addRow("LIGHT0 IR", self.lbl_ir0)
        form.addRow("LIGHT0 Gain", self.lbl_gain0)
        form.addRow("LIGHT0 Int", self.lbl_itime0)
        form.addRow("SQM0 [mag/arcsec²]", self.lbl_sqm0)

        # Light - kanál 1 (mux)
        self.lbl_lux1 = make_label()
        self.lbl_full1 = make_label()
        self.lbl_ir1 = make_label()
        self.lbl_gain1 = make_label()
        self.lbl_itime1 = make_label()
        self.lbl_sqm1 = make_label()
        form.addRow("LIGHT1 Lux", self.lbl_lux1)
        form.addRow("LIGHT1 Full", self.lbl_full1)
        form.addRow("LIGHT1 IR", self.lbl_ir1)
        form.addRow("LIGHT1 Gain", self.lbl_gain1)
        form.addRow("LIGHT1 Int", self.lbl_itime1)
        form.addRow("SQM1 [mag/arcsec²]", self.lbl_sqm1)

        # IR senzor 1 parametry
        self.lbl_vdd1 = make_label()
        self.lbl_ta1 = make_label()
        form.addRow("MLX1 Vdd [V]", self.lbl_vdd1)
        form.addRow("MLX1 Ta [°C]", self.lbl_ta1)

        # Cloud rohy/střed senzor 1
        self.lbl_tl1 = make_label()
        self.lbl_tr1 = make_label()
        self.lbl_bl1 = make_label()
        self.lbl_br1 = make_label()
        self.lbl_ctr1 = make_label()
        form.addRow("S1 TL [°C]", self.lbl_tl1)
        form.addRow("S1 TR [°C]", self.lbl_tr1)
        form.addRow("S1 BL [°C]", self.lbl_bl1)
        form.addRow("S1 BR [°C]", self.lbl_br1)
        form.addRow("S1 CTR [°C]", self.lbl_ctr1)
        
        # IR senzor 2 parametry
        self.lbl_vdd2 = make_label()
        self.lbl_ta2 = make_label()
        form.addRow("MLX2 Vdd [V]", self.lbl_vdd2)
        form.addRow("MLX2 Ta [°C]", self.lbl_ta2)

        # Cloud rohy/střed senzor 2
        self.lbl_tl2 = make_label()
        self.lbl_tr2 = make_label()
        self.lbl_bl2 = make_label()
        self.lbl_br2 = make_label()
        self.lbl_ctr2 = make_label()
        form.addRow("S2 TL [°C]", self.lbl_tl2)
        form.addRow("S2 TR [°C]", self.lbl_tr2)
        form.addRow("S2 BL [°C]", self.lbl_bl2)
        form.addRow("S2 BR [°C]", self.lbl_br2)
        form.addRow("S2 CTR [°C]", self.lbl_ctr2)
        
        # --- Replay controls (skryté dokud není načten soubor) ---
        self.replay_controls = QtWidgets.QWidget()
        self.replay_controls.setStyleSheet(
            "background-color: #2a2a2a; border-top: 1px solid #444;"
        )
        rc_layout = QtWidgets.QVBoxLayout(self.replay_controls)
        rc_layout.setContentsMargins(6, 4, 6, 4)
        rc_layout.setSpacing(3)

        btn_row = QtWidgets.QHBoxLayout()

        self.replay_rewind_btn = QtWidgets.QPushButton("⏮")
        self.replay_rewind_btn.setFixedWidth(36)
        self.replay_rewind_btn.setToolTip("Přesun na začátek")
        self.replay_rewind_btn.clicked.connect(self._replay_rewind)
        btn_row.addWidget(self.replay_rewind_btn)

        self.replay_play_btn = QtWidgets.QPushButton("▶")
        self.replay_play_btn.setFixedWidth(36)
        self.replay_play_btn.setToolTip("Přehrát / Pauza")
        self.replay_play_btn.clicked.connect(self._toggle_replay_play)
        btn_row.addWidget(self.replay_play_btn)

        self.replay_frame_label = QtWidgets.QLabel("0 / 0")
        self.replay_frame_label.setMinimumWidth(80)
        btn_row.addWidget(self.replay_frame_label)

        btn_row.addWidget(QtWidgets.QLabel("Rychlost:"))
        self.replay_speed_combo = QtWidgets.QComboBox()
        self.replay_speed_combo.addItems(["0.5x", "1x", "2x", "5x", "10x", "20x"])
        self.replay_speed_combo.setCurrentIndex(1)
        self.replay_speed_combo.currentTextChanged.connect(self._set_replay_speed)
        btn_row.addWidget(self.replay_speed_combo)

        self.replay_time_label = QtWidgets.QLabel("–")
        self.replay_time_label.setStyleSheet("color: #aaaaff; font-family: monospace;")
        btn_row.addWidget(self.replay_time_label)
        btn_row.addStretch()

        rc_layout.addLayout(btn_row)

        self.replay_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.replay_slider.setRange(0, 0)
        self.replay_slider.sliderMoved.connect(self._seek_replay)
        rc_layout.addWidget(self.replay_slider)

        self.replay_controls.setVisible(False)
        main_vbox.addWidget(self.replay_controls)

        self.tabs.addTab(graph_widget, "Graph")

    def image_hover_event(self, event):
        """Zobrazí hodnotu pod kurzorem."""
        if event.isExit():
            self.value_label.setVisible(False)
            return
        
        pos = event.pos()
        # pos.x() je sloupec (j), pos.y() je řádek (i)
        j, i = int(pos.x()), int(pos.y())
        
        # Kontrola, zda je pozice v rámci obrazu
        if 0 <= i < self.combined_data.shape[0] and 0 <= j < self.combined_data.shape[1]:
            value = self.combined_data[i, j]
            
            # Určení, který senzor
            sensor_width = self.combined_data.shape[1] // 2
            sensor_id = 1 if j < sensor_width else 2
            local_j = j if sensor_id == 1 else j - sensor_width
            
            mode_str = "Cal" if self.show_calibrated else "Raw"
            self.value_label.setText(f"S{sensor_id} [{i},{local_j}]: {value:.2f}°C ({mode_str})")
            self.value_label.setPos(j, i)
            self.value_label.setVisible(True)
        else:
            self.value_label.setVisible(False)
    
    def create_table_tab(self):
        """Vytvoří druhou kartu s tabulkou dat."""
        table_widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(table_widget)
        
        self.data_table = QtWidgets.QTableWidget()
        self.data_table.setColumnCount(2)
        self.data_table.setHorizontalHeaderLabels(["Parameter", "Value"])
        self.data_table.horizontalHeader().setStretchLastSection(True)
        
        # Připrav řádky
        params = [
            "Timestamp",
            "SHT4x Temp [°C]",
            "SHT4x RH [%]",
            "Dew Point [°C]",
            "LIGHT0 Lux",
            "LIGHT0 Full",
            "LIGHT0 IR",
            "LIGHT0 Gain",
            "LIGHT0 Integration",
            "SQM0 [mag/arcsec²]",
            "LIGHT1 Lux",
            "LIGHT1 Full",
            "LIGHT1 IR",
            "LIGHT1 Gain",
            "LIGHT1 Integration",
            "SQM1 [mag/arcsec²]",
            "MLX Vdd [V]",
            "MLX Ta [°C]",
            "Corner TL [°C]",
            "Corner TR [°C]",
            "Corner BL [°C]",
            "Corner BR [°C]",
            "Center [°C]"
        ]
        
        self.data_table.setRowCount(len(params))
        for i, param in enumerate(params):
            self.data_table.setItem(i, 0, QtWidgets.QTableWidgetItem(param))
            self.data_table.setItem(i, 1, QtWidgets.QTableWidgetItem("—"))
        
        layout.addWidget(self.data_table)
        self.tabs.addTab(table_widget, "Data Table")
    
    def create_api_tab(self):
        """Vytvoří třetí kartu s HTTP API."""
        api_widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(api_widget)
        
        # Ovládací prvky
        control_layout = QtWidgets.QHBoxLayout()
        
        self.api_enable_check = QtWidgets.QCheckBox("Enable HTTP API")
        self.api_enable_check.toggled.connect(self.toggle_http_api)
        control_layout.addWidget(self.api_enable_check)
        
        self.api_status_label = QtWidgets.QLabel("Status: Disabled")
        control_layout.addWidget(self.api_status_label)
        control_layout.addStretch()
        
        layout.addLayout(control_layout)
        
        # JSON náhled
        json_label = QtWidgets.QLabel("Current JSON data:")
        layout.addWidget(json_label)
        
        self.json_text = QtWidgets.QPlainTextEdit()
        self.json_text.setReadOnly(True)
        self.json_text.setFont(QtGui.QFont("Monospace", 9))
        layout.addWidget(self.json_text)
        
        # Timer pro aktualizaci JSON náhledu
        self.json_timer = QtCore.QTimer(self)
        self.json_timer.setInterval(1000)  # 1s
        self.json_timer.timeout.connect(self.update_json_preview)
        self.json_timer.start()
        
        self.tabs.addTab(api_widget, "HTTP API")
    
    def show_config(self):
        """Zobrazí konfigurační dialog."""
        dialog = ConfigDialog(self.settings, self)
        if dialog.exec():
            # Aplikuj změny
            self.device_id = self.settings.value("log_name", "AMSKY01")
            if self.logger:
                # Pokud je logování zapnuté, restartuj s novým nastavením
                self.logger.close()
                log_path = self.settings.value("log_path", ".")
                self.logger = HDF5Logger(self.device_id, Path(log_path))
        self._update_log_status()
    
    def toggle_calibrated(self, checked: bool):
        """Přepne mezi raw a kalibrovanými teplotami."""
        self.show_calibrated = checked
        # Překresli obraz s aktuálním režimem
        self._update_combined_image()
    
    def toggle_logging(self, checked: bool):
        """Zapne/vypne logování."""
        if not HDF5_AVAILABLE:
            return
        
        if checked and self.logger is None:
            log_path = self.settings.value("log_path", ".")
            self.logger = HDF5Logger(self.device_id, Path(log_path))
            self.logging_enabled = True
            print("HDF5 logování zapnuto")
        elif not checked and self.logger is not None:
            self.logger.close()
            self.logger = None
            self.logging_enabled = False
            print("HDF5 logování vypnuto")
        
        self._update_log_status()
    
    def _update_log_status(self):
        """Aktualizuje status label pro logování."""
        if self.logging_enabled and self.logger:
            # Zelená pro aktivní logování
            self.lbl_log_status.setText("🟢 LOGGING ACTIVE")
            self.lbl_log_status.setStyleSheet(
                "background-color: #ccffcc; color: #006600; "
                "font-weight: bold; padding: 5px; border-radius: 3px;"
            )
            # Zobraz název souboru ve statusbaru
            if self.logger.current_file:
                filename = self.logger._get_filename(self.logger.current_hour)
                self.statusBar().showMessage(f"Logging to: {filename}")
        else:
            # Červená pro vypnuté logování
            self.lbl_log_status.setText("🔴 Logging OFF")
            self.lbl_log_status.setStyleSheet(
                "background-color: #ffcccc; color: #cc0000; "
                "font-weight: bold; padding: 5px; border-radius: 3px;"
            )
            self.statusBar().showMessage("Not logging")
    
    def toggle_http_api(self, enabled: bool):
        """Zapne/vypne HTTP API server."""
        if enabled:
            port = self.settings.value("http_port", 8080, type=int)
            try:
                DataHTTPHandler.data_source = self
                self.http_server = HTTPServer(("", port), DataHTTPHandler)
                self.http_thread = Thread(target=self.http_server.serve_forever, daemon=True)
                self.http_thread.start()
                self.http_enabled = True
                self.api_status_label.setText(f"Status: Running on port {port}")
                self.api_status_label.setStyleSheet("color: green;")
                print(f"HTTP API started on port {port}")
            except Exception as e:
                self.api_enable_check.setChecked(False)
                QtWidgets.QMessageBox.warning(self, "Error", f"Failed to start HTTP server: {e}")
        else:
            if self.http_server:
                self.http_server.shutdown()
                self.http_server = None
                self.http_thread = None
            self.http_enabled = False
            self.api_status_label.setText("Status: Disabled")
            self.api_status_label.setStyleSheet("color: red;")
            print("HTTP API stopped")
    
    def get_json_data(self):
        """Vrací aktuální data jako dict pro JSON."""
        return self.current_data.copy()
    
    def update_json_preview(self):
        """Aktualizuje JSON náhled v API kartě."""
        if self.tabs.currentIndex() == 2:  # API tab
            json_str = json.dumps(self.current_data, indent=2)
            self.json_text.setPlainText(json_str)
    
    def update_data_table(self):
        """Aktualizuje tabulku dat."""
        if self.tabs.currentIndex() == 1:  # Data table tab
            d = self.current_data
            # MLX/cloud sloupce zobrazují data z prvního senzoru pro kompatibilitu s tabulkou
            values = [
                d["timestamp"] or "—",
                f"{d['hygro']['temp']:.2f}" if d['hygro']['temp'] is not None else "—",
                f"{d['hygro']['rh']:.2f}" if d['hygro']['rh'] is not None else "—",
                f"{d['hygro']['dew_point']:.2f}" if d['hygro']['dew_point'] is not None else "—",
                f"{d['light0']['lux']:.6f}" if d['light0']['lux'] is not None else "—",
                f"{d['light0']['full']:.0f}" if d['light0']['full'] is not None else "—",
                f"{d['light0']['ir']:.0f}" if d['light0']['ir'] is not None else "—",
                d['light0']['gain'] or "—",
                d['light0']['itime'] or "—",
                f"{d['light0']['sqm']:.2f}" if d['light0']['sqm'] is not None else "—",
                f"{d['light1']['lux']:.6f}" if d['light1']['lux'] is not None else "—",
                f"{d['light1']['full']:.0f}" if d['light1']['full'] is not None else "—",
                f"{d['light1']['ir']:.0f}" if d['light1']['ir'] is not None else "—",
                d['light1']['gain'] or "—",
                d['light1']['itime'] or "—",
                f"{d['light1']['sqm']:.2f}" if d['light1']['sqm'] is not None else "—",
                f"{d['mlx1']['vdd']:.3f}" if d['mlx1']['vdd'] is not None else "—",
                f"{d['mlx1']['ta']:.3f}" if d['mlx1']['ta'] is not None else "—",
                f"{d['cloud1']['tl']:.2f}" if d['cloud1']['tl'] is not None else "—",
                f"{d['cloud1']['tr']:.2f}" if d['cloud1']['tr'] is not None else "—",
                f"{d['cloud1']['bl']:.2f}" if d['cloud1']['bl'] is not None else "—",
                f"{d['cloud1']['br']:.2f}" if d['cloud1']['br'] is not None else "—",
                f"{d['cloud1']['center']:.2f}" if d['cloud1']['center'] is not None else "—",
            ]
            
            for i, value in enumerate(values):
                self.data_table.item(i, 1).setText(str(value))

    # --- seriový polling ---

    def poll_serial(self):
        if self.ser is None:
            return
        try:
            # Čti všechny dostupné data
            while self.ser.in_waiting:
                chunk = self.ser.read(self.ser.in_waiting).decode(errors="ignore")
                if not chunk:
                    break
                
                # Přidej do bufferu
                self.line_buffer += chunk
                
                # Zpracuj kompletní řádky
                while "\n" in self.line_buffer:
                    line, self.line_buffer = self.line_buffer.split("\n", 1)
                    if self.debug:
                        print(f"< {line}")
                    self.process_line(line + "\n")
        except serial.SerialException as e:
            print(f"Serial error: {e}")

    def process_line(self, line: str):
        s = line.strip()
        if not s:
            return
        
        # Aktualizuj timestamp
        self.current_data["timestamp"] = datetime.now().isoformat()

        if s.startswith("$thrmap,"):
            result = parse_thrmap(s)
            if result is not None:
                sensor_id, frame = result
                self._update_image(sensor_id, frame)
                
                if sensor_id == 1:
                    self.current_data["thrmap1"] = frame.flatten().tolist()
                    if self.logging_enabled and self.logger and self.last_ta1 is not None:
                        self.logger.log_sky(1, frame, self.last_ta1)
                elif sensor_id == 2:
                    self.current_data["thrmap2"] = frame.flatten().tolist()
                    if self.logging_enabled and self.logger and self.last_ta2 is not None:
                        self.logger.log_sky(2, frame, self.last_ta2)
            return

        if s.startswith("$hygro,"):
            v = parse_hygro(s)
            if v is not None:
                t, rh, dew = v
                self.lbl_temp.setText(f"{t:.2f}")
                self.lbl_rh.setText(f"{rh:.2f}")
                self.lbl_dew.setText(f"{dew:.2f}")
                
                # Ulož hodnoty pro korekci
                self.last_ambient_temp = t
                self.last_humidity = rh
                
                self.current_data["hygro"]["temp"] = t
                self.current_data["hygro"]["rh"] = rh
                self.current_data["hygro"]["dew_point"] = dew
                
                # Loguj do HDF5
                if self.logging_enabled and self.logger:
                    self.logger.log_hygro(t, rh)
                
                self.update_data_table()
            return

        if s.startswith("$light,"):
            v = parse_light(s)
            if v is not None:
                # LIGHT0 a LIGHT1 = TSL2591 na kanálu 0/1 I2C muxu, každý
                # měří jiný výřez oblohy - zobrazují a logují se odděleně.
                channel, lux, full_raw, ir_raw, gain, itime, sqm = v
                lbl_full = self.lbl_full0 if channel == 0 else self.lbl_full1
                lbl_ir = self.lbl_ir0 if channel == 0 else self.lbl_ir1
                lbl_gain = self.lbl_gain0 if channel == 0 else self.lbl_gain1
                lbl_itime = self.lbl_itime0 if channel == 0 else self.lbl_itime1
                lbl_sqm = self.lbl_sqm0 if channel == 0 else self.lbl_sqm1
                lbl_lux = self.lbl_lux0 if channel == 0 else self.lbl_lux1
                data_key = f"light{channel}"

                lbl_full.setText(f"{full_raw:.0f}")
                lbl_ir.setText(f"{ir_raw:.0f}")
                lbl_gain.setText(gain)
                lbl_itime.setText(itime)

                # Vypočítej lux z raw dat pomocí TSL2591 algoritmu
                tsl_lux_calc = calculate_tsl2591_lux(int(full_raw), int(ir_raw), gain, itime)
                if tsl_lux_calc >= 0:
                    lbl_lux.setText(f"{tsl_lux_calc:.2f}")
                    self.current_data[data_key]["lux"] = tsl_lux_calc
                else:
                    lbl_lux.setText("OVERFLOW")
                    self.current_data[data_key]["lux"] = None

                self.current_data[data_key]["full"] = full_raw
                self.current_data[data_key]["ir"] = ir_raw
                self.current_data[data_key]["gain"] = gain
                self.current_data[data_key]["itime"] = itime
                # Vypočítej SQM z raw dat
                sqm_calc = calculate_sqm(int(full_raw), int(ir_raw), float(itime.rstrip('ms')), float(gain_str_to_float(gain)), self.sqm_zp)
                if sqm_calc != float("inf"):
                    lbl_sqm.setText(f"{sqm_calc:.2f}")
                    self.current_data[data_key]["sqm"] = sqm_calc
                else:
                    lbl_sqm.setText("∞")
                    self.current_data[data_key]["sqm"] = None

                # Loguj do HDF5
                if self.logging_enabled and self.logger:
                    try:
                        gain_map = {"1x": 1.0, "16x": 16.0, "25x": 25.0, "400x": 400.0, "428x": 428.0}
                        gain_val = gain_map.get(gain, 1.0)

                        expo_map = {"100ms": 100.0, "200ms": 200.0, "300ms": 300.0, "400ms": 400.0, "500ms": 500.0, "600ms": 600.0}
                        expo_val = expo_map.get(itime, 100.0)

                        self.logger.log_light(channel, full_raw, ir_raw, gain_val, expo_val)
                    except Exception as e:
                        if self.debug:
                            print(f"Error logging light: {e}")

                self.update_data_table()
            return

        if s.startswith("$cloud_meta,"):
            v = parse_cloud_meta(s)
            if v is not None:
                sensor_id, vdd, ta = v
                
                if sensor_id == 1:
                    self.lbl_vdd1.setText(f"{vdd:.3f}")
                    self.lbl_ta1.setText(f"{ta:.3f}")
                    self.last_ta1 = ta
                    self.last_vdd1 = vdd
                    self.current_data["mlx1"]["vdd"] = vdd
                    self.current_data["mlx1"]["ta"] = ta
                elif sensor_id == 2:
                    self.lbl_vdd2.setText(f"{vdd:.3f}")
                    self.lbl_ta2.setText(f"{ta:.3f}")
                    self.last_ta2 = ta
                    self.last_vdd2 = vdd
                    self.current_data["mlx2"]["vdd"] = vdd
                    self.current_data["mlx2"]["ta"] = ta
                
                self.update_data_table()
            return

        if s.startswith("$cloud,"):
            v = parse_cloud(s)
            if v is not None:
                sensor_id, tl, tr, bl, br, ctr = v
                
                if sensor_id == 1:
                    self.lbl_tl1.setText(f"{tl:.2f}")
                    self.lbl_tr1.setText(f"{tr:.2f}")
                    self.lbl_bl1.setText(f"{bl:.2f}")
                    self.lbl_br1.setText(f"{br:.2f}")
                    self.lbl_ctr1.setText(f"{ctr:.2f}")
                    self.current_data["cloud1"]["tl"] = tl
                    self.current_data["cloud1"]["tr"] = tr
                    self.current_data["cloud1"]["bl"] = bl
                    self.current_data["cloud1"]["br"] = br
                    self.current_data["cloud1"]["center"] = ctr
                    if self.logging_enabled and self.logger:
                        self.logger.log_cloud(1, tl, tr, bl, br, ctr, self.last_vdd1)
                elif sensor_id == 2:
                    self.lbl_tl2.setText(f"{tl:.2f}")
                    self.lbl_tr2.setText(f"{tr:.2f}")
                    self.lbl_bl2.setText(f"{bl:.2f}")
                    self.lbl_br2.setText(f"{br:.2f}")
                    self.lbl_ctr2.setText(f"{ctr:.2f}")
                    self.current_data["cloud2"]["tl"] = tl
                    self.current_data["cloud2"]["tr"] = tr
                    self.current_data["cloud2"]["bl"] = bl
                    self.current_data["cloud2"]["br"] = br
                    self.current_data["cloud2"]["center"] = ctr
                    if self.logging_enabled and self.logger:
                        self.logger.log_cloud(2, tl, tr, bl, br, ctr, self.last_vdd2)

                self.update_data_table()
            return

    # --- update obrazu ---

    def _update_image(self, sensor_id: int, frame: np.ndarray):
        # Ulož data pro příslušný senzor a označ ho jako připravený
        if sensor_id == 1:
            self.img_data1[:] = frame
            self.sensor1_ready = True
        elif sensor_id == 2:
            self.img_data2[:] = frame
            self.sensor2_ready = True
        else:
            return
        
        # Aktualizuj kombinovaný obraz
        self._update_combined_image()
    
    def _update_combined_image(self):
        """Spojí oba senzory do jedné matice s otočením o 90° doleva."""
        # Nezobrazuj nic, dokud žádný senzor nemá data
        if not self.sensor1_ready and not self.sensor2_ready:
            return
        
        # Otočení o 90° doleva = rot90(frame, k=1)
        # frame je 12x16, po otočení bude 16x12
        rotated1 = np.rot90(self.img_data1, k=1)
        rotated2 = np.rot90(self.img_data2, k=1)
        
        # Aplikuj korekci, pokud je zapnuta
        if self.show_calibrated:
            # Potřebujeme Ta (ambient temp) a RH (humidity) a Tchip (Ta z MLX)
            # Pro senzor 1 použijeme last_ta1, pro senzor 2 last_ta2
            if self.last_ta1 is not None:
                rotated1 = apply_sky_temperature_correction(
                    rotated1, 
                    self.last_ambient_temp, 
                    self.last_humidity, 
                    self.last_ta1
                )
            
            if self.last_ta2 is not None:
                rotated2 = apply_sky_temperature_correction(
                    rotated2, 
                    self.last_ambient_temp, 
                    self.last_humidity, 
                    self.last_ta2
                )
        
        # Spojíme oba obrazy vedle sebe horizontálně
        # rotated1: 16x12, rotated2: 16x12 -> combined: 16x24
        self.combined_data = np.hstack([rotated1, rotated2])
        
        if self.vmin is None or self.vmax is None:
            # Auto mode - vypočti min/max ignorujíce NaN (nepřipravené senzory)
            valid = self.combined_data[np.isfinite(self.combined_data)]
            if valid.size == 0:
                return
            levels = (float(valid.min()), float(valid.max()))
            self.img_item.setImage(self.combined_data, autoLevels=False, levels=levels)
        else:
            # Fixed mode - použij uživatelem zadané hodnoty
            self.img_item.setImage(self.combined_data, autoLevels=False)

        if (self.vmin is not None and self.vmax is not None) and not self.levels_initialized:
            # Nastav limity pouze jednou při prvním snímku
            try:
                self.hist_lut.setLevels(self.vmin, self.vmax)
                self.levels_initialized = True
            except Exception:
                pass
    
    # --- Replay ---

    def _open_replay_file_dialog(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Otevřít log soubor", ".", "HDF5 soubory (*.h5 *.hdf5)"
        )
        if path:
            self._load_replay_data(path)

    def _load_replay_data(self, filepath):
        if not HDF5_AVAILABLE:
            QtWidgets.QMessageBox.warning(self, "Chyba", "h5py není dostupné")
            return
        try:
            with h5py.File(filepath, 'r') as f:
                # Nový formát: /sky1 a /sky2; starý formát: /sky (jen senzor 1)
                if 'sky1' in f:
                    sky1_data = f['sky1']['data'][:]
                    sky1_time = f['sky1']['time'][:]
                    sky1_temp = f['sky1']['temp'][:]
                    sky2_data = f['sky2']['data'][:] if 'sky2' in f else np.full((0, ROWS, COLS), np.nan, dtype=np.float32)
                    sky2_time = f['sky2']['time'][:] if 'sky2' in f else np.array([], dtype=np.int64)
                    sky2_temp = f['sky2']['temp'][:] if 'sky2' in f else np.array([], dtype=np.float32)
                else:
                    # Starý formát – zpětná kompatibilita
                    sky1_data = f['sky']['data'][:]
                    sky1_time = f['sky']['time'][:]
                    sky1_temp = f['sky']['temp'][:]
                    sky2_data = np.full((0, ROWS, COLS), np.nan, dtype=np.float32)
                    sky2_time = np.array([], dtype=np.int64)
                    sky2_temp = np.array([], dtype=np.float32)

                self.replay_data = {
                    'sky1_data': sky1_data,
                    'sky1_time': sky1_time,
                    'sky1_temp': sky1_temp,
                    'sky2_data': sky2_data,
                    'sky2_time': sky2_time,
                    'sky2_temp': sky2_temp,
                    'hygro_temp': f['hygro']['temp'][:] if 'hygro' in f else np.array([]),
                    'hygro_hum':  f['hygro']['hum'][:]  if 'hygro' in f else np.array([]),
                    'hygro_time': f['hygro']['time'][:] if 'hygro' in f else np.array([]),
                }

                # Nový formát: /light0 a /light1 (odděleně dle kanálu muxu);
                # starý formát (jednokanálový): /light -> naplní se jen light0.
                for ch in (0, 1):
                    gname = f"light{ch}"
                    if gname in f:
                        self.replay_data[f'light{ch}_all'] = f[gname]['all'][:]
                        self.replay_data[f'light{ch}_ir'] = f[gname]['ir'][:]
                        self.replay_data[f'light{ch}_gain'] = f[gname]['gain'][:]
                        self.replay_data[f'light{ch}_expo'] = f[gname]['expo'][:]
                        self.replay_data[f'light{ch}_time'] = f[gname]['time'][:]
                    elif ch == 0 and 'light' in f:
                        self.replay_data['light0_all'] = f['light']['all'][:]
                        self.replay_data['light0_ir'] = f['light']['ir'][:]
                        self.replay_data['light0_gain'] = f['light']['gain'][:]
                        self.replay_data['light0_expo'] = f['light']['expo'][:]
                        self.replay_data['light0_time'] = f['light']['time'][:]
                    else:
                        self.replay_data[f'light{ch}_all'] = np.array([])
                        self.replay_data[f'light{ch}_ir'] = np.array([])
                        self.replay_data[f'light{ch}_gain'] = np.array([])
                        self.replay_data[f'light{ch}_expo'] = np.array([])
                        self.replay_data[f'light{ch}_time'] = np.array([])

            n = len(self.replay_data['sky1_data'])
            n2 = len(self.replay_data['sky2_data'])
            print(f"Replay: načteno {n} snímků (S1) + {n2} snímků (S2) z {filepath}")

            self.replay_frame_idx = 0
            self.replay_playing = False
            self.replay_play_btn.setText("▶")
            self.replay_start_real = None
            self.replay_start_data_ns = None

            self.replay_slider.setRange(0, max(0, n - 1))
            self.replay_frame_label.setText(f"0 / {n}")
            self.replay_controls.setVisible(True)

            # Disable serial logging in replay mode
            self.log_action.setEnabled(False)

            if n > 0:
                self._display_replay_frame(0)

            self.setWindowTitle(f"AMSKY01 Replay — {os.path.basename(filepath)}")
            self.statusBar().showMessage(f"Replay: {os.path.basename(filepath)}  ({n} snímků)")

        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Chyba", f"Nelze načíst soubor:\n{e}")
            self.replay_data = None

    def _on_poll_timer(self):
        if self.replay_data is not None:
            self.poll_replay()
        elif self.ser is not None:
            self.poll_serial()

    def poll_replay(self):
        if not self.replay_playing or self.replay_data is None:
            return

        sky_time = self.replay_data['sky1_time']
        n = len(sky_time)
        if n == 0:
            return

        if self.replay_start_real is None:
            self.replay_start_real = time.time()
            self.replay_start_data_ns = sky_time[self.replay_frame_idx]

        elapsed_ns = (time.time() - self.replay_start_real) * self.replay_speed * 1e9
        target_ts  = self.replay_start_data_ns + elapsed_ns
        target_idx = int(np.searchsorted(sky_time, target_ts))
        target_idx = min(target_idx, n - 1)

        if target_idx > self.replay_frame_idx:
            self.replay_frame_idx = target_idx
            self._display_replay_frame(self.replay_frame_idx)

        if self.replay_frame_idx >= n - 1:
            self.replay_playing = False
            self.replay_play_btn.setText("▶")

    def _display_replay_frame(self, idx):
        d = self.replay_data
        sky1_data = d['sky1_data']
        sky1_time = d['sky1_time']
        sky2_data = d['sky2_data']
        sky2_time = d['sky2_time']
        n = len(sky1_data)

        if idx >= n:
            return

        frame1 = sky1_data[idx]
        ts_ns  = sky1_time[idx]

        # Senzor 1
        self._update_image(1, frame1)

        # Senzor 2 – nejbližší snímek dle timestamp
        if len(sky2_time) > 0:
            si2 = min(int(np.searchsorted(sky2_time, ts_ns)), len(sky2_data) - 1)
            self._update_image(2, sky2_data[si2])

        # Timestamp
        dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
        time_str = dt.strftime('%Y-%m-%d %H:%M:%S UTC')
        self.replay_time_label.setText(time_str)
        self.replay_frame_label.setText(f"{idx + 1} / {n}")
        self.current_data["timestamp"] = dt.isoformat()

        # Slider (bez zpětného volání)
        self.replay_slider.blockSignals(True)
        self.replay_slider.setValue(idx)
        self.replay_slider.blockSignals(False)

        # Hygro (nejbližší vzorek k aktuálnímu timestamp)
        if len(d['hygro_time']) > 0:
            hi = int(np.searchsorted(d['hygro_time'], ts_ns))
            hi = min(hi, len(d['hygro_temp']) - 1)
            t  = float(d['hygro_temp'][hi])
            rh = float(d['hygro_hum'][hi])
            dew = dewpoint_magnus(t, rh)
            self.lbl_temp.setText(f"{t:.2f}")
            self.lbl_rh.setText(f"{rh:.2f}")
            self.lbl_dew.setText(f"{dew:.2f}")
            self.last_ambient_temp = t
            self.last_humidity = rh
            self.current_data["hygro"].update({"temp": t, "rh": rh, "dew_point": dew})

        # Light (pokud dostupné) - kanál 0 a 1 zvlášť
        light_labels = {
            0: (self.lbl_full0, self.lbl_ir0, self.lbl_gain0, self.lbl_itime0, self.lbl_sqm0),
            1: (self.lbl_full1, self.lbl_ir1, self.lbl_gain1, self.lbl_itime1, self.lbl_sqm1),
        }
        for ch in (0, 1):
            time_arr = d[f'light{ch}_time']
            if len(time_arr) == 0:
                continue
            li = int(np.searchsorted(time_arr, ts_ns))
            li = min(li, len(d[f'light{ch}_all']) - 1)
            full = float(d[f'light{ch}_all'][li])
            ir   = float(d[f'light{ch}_ir'][li])
            gain = float(d[f'light{ch}_gain'][li])
            expo = float(d[f'light{ch}_expo'][li])
            lbl_full, lbl_ir, lbl_gain, lbl_itime, lbl_sqm = light_labels[ch]
            lbl_full.setText(f"{full:.0f}")
            lbl_ir.setText(f"{ir:.0f}")
            lbl_gain.setText(f"{gain:.0f}x")
            lbl_itime.setText(f"{expo:.0f}ms")
            sqm_val = calculate_sqm(int(full), int(ir), expo, gain, self.sqm_zp)
            lbl_sqm.setText(f"{sqm_val:.2f}" if sqm_val != float('inf') else "∞")

        # MLX Ta z uložené teploty čipu
        chip_ta1 = float(d['sky1_temp'][idx])
        self.lbl_ta1.setText(f"{chip_ta1:.3f}")
        self.last_ta1 = chip_ta1
        if len(d['sky2_time']) > 0:
            si2 = min(int(np.searchsorted(d['sky2_time'], ts_ns)), len(d['sky2_temp']) - 1)
            chip_ta2 = float(d['sky2_temp'][si2])
            self.lbl_ta2.setText(f"{chip_ta2:.3f}")
            self.last_ta2 = chip_ta2

        self.update_data_table()

    def _toggle_replay_play(self):
        if self.replay_data is None:
            return
        if self.replay_playing:
            self.replay_playing = False
            self.replay_play_btn.setText("▶")
        else:
            n = len(self.replay_data['sky1_time'])
            if self.replay_frame_idx >= n - 1:
                self.replay_frame_idx = 0
            self.replay_playing = True
            self.replay_play_btn.setText("⏸")
            self.replay_start_real = None
            self.replay_start_data_ns = None

    def _replay_rewind(self):
        self.replay_playing = False
        self.replay_play_btn.setText("▶")
        self.replay_start_real = None
        self.replay_start_data_ns = None
        self.replay_frame_idx = 0
        if self.replay_data and len(self.replay_data['sky_data']) > 0:
            self._display_replay_frame(0)

    def _seek_replay(self, value):
        self.replay_frame_idx = value
        self.replay_start_real = None
        self.replay_start_data_ns = None
        if self.replay_data:
            self._display_replay_frame(value)

    def _set_replay_speed(self, speed_str):
        speeds = {"0.5x": 0.5, "1x": 1.0, "2x": 2.0, "5x": 5.0, "10x": 10.0, "20x": 20.0}
        self.replay_speed = speeds.get(speed_str, 1.0)
        if self.replay_playing:
            self.replay_start_real = None
            self.replay_start_data_ns = None

    def closeEvent(self, event):
        """Při zavírání okna zavři i HDF5 soubor a HTTP server."""
        if self.logger is not None:
            self.logger.close()
        if self.http_server is not None:
            self.http_server.shutdown()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="Melexis AMSKY01 vizualizátor (PyQtGraph)")
    parser.add_argument("--port", default=None, help="seriový port, např. /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200, help="baudrate (default 115200)")
    parser.add_argument("--replay", type=str, default=None, metavar="FILE",
                        help="HDF5 log soubor pro přehrávání (alternativa k --port)")
    parser.add_argument("--replay-speed", type=float, default=1.0,
                        help="rychlost přehrávání, např. 2.0 = 2× (default 1.0)")
    parser.add_argument("--vmin", type=float, default=None, help="min. teplota pro barevnou škálu")
    parser.add_argument("--vmax", type=float, default=None, help="max. teplota pro barevnou škálu")
    parser.add_argument("--rotation", type=float, default=0.0, help="rotace obrazu ve stupních")
    parser.add_argument("--debug", action="store_true", help="zobraz všechny zprávy na seriové lince")
    parser.add_argument("--log", action="store_true", help="zapni HDF5 logování při startu")
    parser.add_argument("--api", action="store_true", help="zapni HTTP API při startu")
    parser.add_argument("--log-name", type=str, default=None, help="ID zařízení pro názvy HDF5 souborů")
    parser.add_argument("--log-path", type=str, default=None, help="cesta pro ukládání HDF5 souborů")
    parser.add_argument("--sqm-zp", type=float, default=24.0, help="SQM kalibrační konstanta (výchozí: 24.0)")
    parser.add_argument("--headless", "--no-gui", dest="headless", action="store_true",
                        help="běh bez GUI — pouze parsování a logování ze seriové linky")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="vypisuj přijímané hodnoty na stdout")
    parser.add_argument("--stats-interval", type=float, default=10.0,
                        help="interval [s] pro souhrnný status v headless režimu (default 10)")

    args = parser.parse_args()

    if args.headless:
        if args.port is None:
            print("Chyba: --headless vyžaduje --port", file=sys.stderr)
            sys.exit(2)
        try:
            ser = serial.Serial(args.port, args.baud, timeout=0)
        except serial.SerialException as e:
            print(f"Nelze otevřít port {args.port}: {e}", file=sys.stderr)
            sys.exit(1)
        try:
            ser.write(b"thrmap_on\n")
            if args.verbose:
                print("> thrmap_on")
        except serial.SerialException:
            pass

        device_id = args.log_name or "AMSKY01"
        log_path = args.log_path or "."
        runner = HeadlessRunner(
            ser,
            device_id=device_id,
            log_path=log_path,
            enable_logging=args.log,
            verbose=args.verbose,
            sqm_zp=args.sqm_zp,
            stats_interval=args.stats_interval,
        )
        rc = runner.run()
        try:
            ser.close()
        except Exception:
            pass
        sys.exit(rc)

    if args.port is None and args.replay is None:
        # Spuštění bez argumentů – dialog pro výběr souboru se otevře po startu
        print("Tip: zadejte --port nebo --replay, nebo použijte File > Open Replay File...")

    ser = None
    if args.port:
        try:
            ser = serial.Serial(args.port, args.baud, timeout=0)
        except serial.SerialException as e:
            print(f"Nelze otevřít port {args.port}: {e}")
            sys.exit(1)
        try:
            ser.write(b"thrmap_on\n")
            if args.debug:
                print("> thrmap_on")
        except serial.SerialException:
            pass

    app = QtWidgets.QApplication(sys.argv)
    
    # Nastavení dark mode (PySide6 >= 6.4 vyžaduje ColorRole.*)
    _cr = QtGui.QPalette.ColorRole
    palette = QtGui.QPalette()
    palette.setColor(_cr.Window,          QtGui.QColor(53, 53, 53))
    palette.setColor(_cr.WindowText,      QtGui.QColor(255, 255, 255))
    palette.setColor(_cr.Base,            QtGui.QColor(35, 35, 35))
    palette.setColor(_cr.AlternateBase,   QtGui.QColor(53, 53, 53))
    palette.setColor(_cr.ToolTipBase,     QtGui.QColor(25, 25, 25))
    palette.setColor(_cr.ToolTipText,     QtGui.QColor(255, 255, 255))
    palette.setColor(_cr.Text,            QtGui.QColor(255, 255, 255))
    palette.setColor(_cr.Button,          QtGui.QColor(53, 53, 53))
    palette.setColor(_cr.ButtonText,      QtGui.QColor(255, 255, 255))
    palette.setColor(_cr.BrightText,      QtGui.QColor(255, 0, 0))
    palette.setColor(_cr.Link,            QtGui.QColor(42, 130, 218))
    palette.setColor(_cr.Highlight,       QtGui.QColor(42, 130, 218))
    palette.setColor(_cr.HighlightedText, QtGui.QColor(35, 35, 35))
    app.setPalette(palette)
    
    # Nastavení stylu widgetů
    app.setStyleSheet("""
        QToolTip { 
            color: #ffffff; 
            background-color: #2a2a2a; 
            border: 1px solid #555555; 
        }
        QMenuBar {
            background-color: #353535;
            color: #ffffff;
        }
        QMenuBar::item:selected {
            background-color: #2a82da;
        }
        QMenu {
            background-color: #353535;
            color: #ffffff;
            border: 1px solid #555555;
        }
        QMenu::item:selected {
            background-color: #2a82da;
        }
    """)
    
    # Nastavení aplikace pro QSettings
    app.setOrganizationName("AstroMeters")
    app.setApplicationName("AMSKY01Viewer")
    
    win = MainWindow(
        ser,
        vmin=args.vmin,
        vmax=args.vmax,
        rotation=args.rotation,
        debug=args.debug,
        enable_logging=args.log,
        enable_http_api=args.api,
        device_id=args.log_name,
        log_path=args.log_path,
        sqm_zp=args.sqm_zp,
        replay_file=args.replay,
        replay_speed=args.replay_speed,
    )
    win.resize(1100, 650)
    win.show()

    # Pokud není zadán port ani replay soubor, otevři dialog pro výběr souboru
    if args.port is None and args.replay is None and HDF5_AVAILABLE:
        QtCore.QTimer.singleShot(200, win._open_replay_file_dialog)

    ret = app.exec()

    if ser is not None:
        ser.close()
    sys.exit(ret)


if __name__ == "__main__":
    main()
