# AMSKY01 Software Tools

Nástroje pro práci se senzory AMSKY01 (MLX90641, SHT4x, TSL2591).

## Nástroje pro real-time monitoring

### `amsky01_viewer.py`
GUI vizualizátor s PyQt/PyQtGraph pro zobrazení dat v reálném čase:
- IR teplotní mapa z MLX90641 (12×16 pixelů)
- Teplota a vlhkost ze SHT4x včetně dew pointu
- Osvětlení z TSL2591 včetně SQM
- Parametry senzorů (Vdd, Ta, rohy IR mapy)

**Použití:**
```bash
python amsky01_viewer.py --port /dev/ttyACM0 --baud 115200
python amsky01_viewer.py --port /dev/ttyACM0 --debug  # s výpisem komunikace
```

**Závislosti:** `pyserial`, `numpy`, `pyqtgraph`, `PyQt5`

---

### `amsky01_cli.py`
CLI viewer s curses rozhraním + automatické logování do CSV:
- Real-time zobrazení senzorových dat v terminálu
- Automatické ukládání dat do CSV souborů
- Rotace log souborů každých 10 minut

**Použití:**
```bash
python amsky01_cli.py --port /dev/ttyACM0 --baud 115200
```

**Závislosti:** `pyserial`, `curses`

---

## Nástroje pro analýzu logů

### `plot_logs.py`
Vykreslování grafů z uložených CSV logů:
- Podpora více souborů současně
- Interaktivní režim s auto-refresh
- Export do PNG

**Použití:**
```bash
python plot_logs.py sensor_logs/latest.csv
python plot_logs.py --interactive --refresh 30 sensor_logs/*.csv
python plot_logs.py --output myplot.png sensor_logs/data.csv
```

**Závislosti:** `pandas`, `matplotlib`, `numpy`

---

### `plot_latest.sh`
Bash wrapper pro rychlé vykreslení logů:
```bash
./plot_latest.sh              # Vykreslí nejnovější log
./plot_latest.sh --all        # Vykreslí všechny logy
./plot_latest.sh specific.csv # Vykreslí konkrétní soubor
```

---

## Formát UART zpráv

Zařízení komunikuje přes UART rychlostí 115200 baud (konfigurovatelné). Zprávy:

- `$thrmap,<192 hodnot>` - IR teplotní mapa (12×16 pixelů)
- `$cloud,<TL>,<TR>,<BL>,<BR>,<CENTER>` - Rohy a střed IR mapy
- `$cloud_meta,<Vdd>,<Ta>` - Napětí a teplota MLX90641
- `$hygro,<temp>,<humidity>,<dew_point>` - Teplota, vlhkost, rosný bod
- `$light,<lux>,<full>,<ir>,<gain>,<int_time>,<sqm>` - Osvětlení a SQM

---

## Instalace závislostí

```bash
pip install pyserial numpy pyqtgraph PyQt5 pandas matplotlib
```
