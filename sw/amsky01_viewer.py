"""Melexis AMSKY01 vizualizátor dat z UARTu.

Zobrazuje:
- IR mapu z MLX90641 ($thrmap)
- Ta/Vdd z MLX90641 ($cloud_meta)
- rohy/střed z MLX90641 ($cloud)
- teplotu a vlhkost ze SHT4x ($hygro)
- osvětlení z TSL2591 ($light) včetně SQM

Závislosti:
    pip install pyserial numpy pyqtgraph PyQt5

Spuštění (příklad):
    python melexis.py --port /dev/ttyACM0 --baud 115200
"""

import argparse
import sys

import numpy as np
import serial
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore


ROWS = 12
COLS = 16
PIXELS = ROWS * COLS


def parse_thrmap(line: str):
    line = line.strip()
    if not line.startswith("$thrmap,"):
        return None

    parts = line.split(",")
    if len(parts) != 1 + PIXELS:
        return None

    try:
        values = np.array([float(x) for x in parts[1:]], dtype=np.float32)
    except ValueError:
        return None

    frame = values.reshape((ROWS, COLS))
    return frame


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
    """$light,normalized_lux,full_raw,ir_raw,gain,integration_time,sqm"""
    line = line.strip()
    if not line.startswith("$light,"):
        return None
    parts = line.split(",")
    if len(parts) < 7:
        return None
    try:
        lux = float(parts[1])
        full_raw = float(parts[2])
        ir_raw = float(parts[3])
        gain = parts[4]
        itime = parts[5]
        sqm = float(parts[6])
    except ValueError:
        return None
    return lux, full_raw, ir_raw, gain, itime, sqm


def parse_cloud_meta(line: str):
    """$cloud_meta,<vdd>,<ta>"""
    line = line.strip()
    if not line.startswith("$cloud_meta,"):
        return None
    parts = line.split(",")
    if len(parts) < 3:
        return None
    try:
        vdd = float(parts[1])
        ta = float(parts[2])
    except ValueError:
        return None
    return vdd, ta


def parse_cloud(line: str):
    """$cloud,TL,TR,BL,BR,CENTER"""
    line = line.strip()
    if not line.startswith("$cloud,"):
        return None
    parts = line.split(",")
    if len(parts) < 6:
        return None
    try:
        tl = float(parts[1])
        tr = float(parts[2])
        bl = float(parts[3])
        br = float(parts[4])
        center = float(parts[5])
    except ValueError:
        return None
    return tl, tr, bl, br, center


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, ser: serial.Serial, vmin=None, vmax=None, debug=False, parent=None):
        super().__init__(parent)
        self.ser = ser
        self.vmin = vmin
        self.vmax = vmax
        self.debug = debug
        self.line_buffer = ""  # Buffer pro neúplné řádky

        self.setWindowTitle("AMSKY01 / MLX90641 vizualizátor")

        # --- layout ---
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        hbox = QtWidgets.QHBoxLayout(central)

        # Levá část: IR obraz
        self.graphics = pg.GraphicsLayoutWidget()
        hbox.addWidget(self.graphics, 2)

        self.view = self.graphics.addViewBox()
        self.view.setAspectLocked(True)
        self.img_item = pg.ImageItem()
        self.view.addItem(self.img_item)

        # HistogramLUTItem funguje jako colorbar + nastavení barevné mapy
        self.hist_lut = pg.HistogramLUTItem()
        self.graphics.addItem(self.hist_lut)
        self.hist_lut.setImageItem(self.img_item)
        try:
            # barevná mapa "inferno" (pokud je k dispozici)
            self.hist_lut.gradient.loadPreset("inferno")
        except Exception:
            pass

        # Inicializační data
        self.img_data = np.zeros((ROWS, COLS), dtype=np.float32)
        self._update_image(self.img_data)

        # Pravá část: textové hodnoty
        right_panel = QtWidgets.QWidget()
        hbox.addWidget(right_panel, 1)
        form = QtWidgets.QFormLayout(right_panel)

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

        # Light
        self.lbl_lux = make_label()
        self.lbl_full = make_label()
        self.lbl_ir = make_label()
        self.lbl_gain = make_label()
        self.lbl_itime = make_label()
        self.lbl_sqm = make_label()
        form.addRow("Lux", self.lbl_lux)
        form.addRow("TSL full", self.lbl_full)
        form.addRow("TSL IR", self.lbl_ir)
        form.addRow("TSL gain", self.lbl_gain)
        form.addRow("TSL int", self.lbl_itime)
        form.addRow("SQM [mag/arcsec²]", self.lbl_sqm)

        # IR senzor parametry
        self.lbl_vdd = make_label()
        self.lbl_ta = make_label()
        form.addRow("MLX Vdd [V]", self.lbl_vdd)
        form.addRow("MLX Ta [°C]", self.lbl_ta)

        # Cloud rohy/střed
        self.lbl_tl = make_label()
        self.lbl_tr = make_label()
        self.lbl_bl = make_label()
        self.lbl_br = make_label()
        self.lbl_ctr = make_label()
        form.addRow("TL [°C]", self.lbl_tl)
        form.addRow("TR [°C]", self.lbl_tr)
        form.addRow("BL [°C]", self.lbl_bl)
        form.addRow("BR [°C]", self.lbl_br)
        form.addRow("CTR [°C]", self.lbl_ctr)

        # Timer na polling seriáku
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(50)  # ms
        self.timer.timeout.connect(self.poll_serial)
        self.timer.start()

    # --- seriový polling ---

    def poll_serial(self):
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

        if s.startswith("$thrmap,"):
            frame = parse_thrmap(s)
            if frame is not None:
                self._update_image(frame)
            return

        if s.startswith("$hygro,"):
            v = parse_hygro(s)
            if v is not None:
                t, rh, dew = v
                self.lbl_temp.setText(f"{t:.2f}")
                self.lbl_rh.setText(f"{rh:.2f}")
                self.lbl_dew.setText(f"{dew:.2f}")
            return

        if s.startswith("$light,"):
            v = parse_light(s)
            if v is not None:
                lux, full_raw, ir_raw, gain, itime, sqm = v
                self.lbl_lux.setText(f"{lux:.2f}")
                self.lbl_full.setText(f"{full_raw:.0f}")
                self.lbl_ir.setText(f"{ir_raw:.0f}")
                self.lbl_gain.setText(gain)
                self.lbl_itime.setText(itime)
                self.lbl_sqm.setText(f"{sqm:.2f}")
            return

        if s.startswith("$cloud_meta,"):
            v = parse_cloud_meta(s)
            if v is not None:
                vdd, ta = v
                self.lbl_vdd.setText(f"{vdd:.3f}")
                self.lbl_ta.setText(f"{ta:.3f}")
            return

        if s.startswith("$cloud,"):
            v = parse_cloud(s)
            if v is not None:
                tl, tr, bl, br, ctr = v
                self.lbl_tl.setText(f"{tl:.2f}")
                self.lbl_tr.setText(f"{tr:.2f}")
                self.lbl_bl.setText(f"{bl:.2f}")
                self.lbl_br.setText(f"{br:.2f}")
                self.lbl_ctr.setText(f"{ctr:.2f}")
            return

        # případné jiné debug řádky si můžeš odkomentovat
        # print(s)

    # --- update obrazu ---

    def _update_image(self, frame: np.ndarray):
        self.img_data[:] = frame

        if self.vmin is None or self.vmax is None:
            vmin = float(np.nanmin(self.img_data))
            vmax = float(np.nanmax(self.img_data))
            auto_levels = True
        else:
            vmin = self.vmin
            vmax = self.vmax
            auto_levels = False

        # aktualizuj obraz; autoLevels používáme jen pokud uživatel nedefinoval rozsah
        self.img_item.setImage(self.img_data, autoLevels=auto_levels)

        # Nastav úrovně i v HistogramLUTItem (colorbar)
        try:
            self.hist_lut.setLevels(vmin, vmax)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Melexis AMSKY01 vizualizátor (PyQtGraph)")
    parser.add_argument("--port", required=True, help="seriový port, např. /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200, help="baudrate (default 115200)")
    parser.add_argument("--vmin", type=float, default=None, help="min. teplota pro barevnou škálu")
    parser.add_argument("--vmax", type=float, default=None, help="max. teplota pro barevnou škálu")
    parser.add_argument("--debug", action="store_true", help="zobraz všechny zprávy na seriové lince")

    args = parser.parse_args()

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0)
    except serial.SerialException as e:
        print(f"Nelze otevřít port {args.port}: {e}")
        sys.exit(1)

    # Po startu automaticky zapni režim streamování heatmapy
    try:
        cmd = b"thrmap_on\n"
        ser.write(cmd)
        if args.debug:
            print(f"> {cmd.decode().rstrip()}")
    except serial.SerialException:
        pass

    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(ser, vmin=args.vmin, vmax=args.vmax, debug=args.debug)
    win.resize(900, 500)
    win.show()

    ret = app.exec()

    ser.close()
    sys.exit(ret)


if __name__ == "__main__":
    main()
