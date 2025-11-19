# AMSKY01 Software Tools

Tools for working with AMSKY01 sensors (MLX90641, SHT4x, TSL2591).

## Real-time Monitoring Tools

### `amsky01_viewer.py`
GUI visualizer with PyQt/PyQtGraph for real-time data display:
- IR thermal map from MLX90641 (12×16 pixels)
- Temperature and humidity from SHT4x including dew point
- Light from TSL2591 including SQM
- Sensor parameters (Vdd, Ta, IR map corners)

**Usage:**
```bash
python amsky01_viewer.py --port /dev/ttyACM0 --baud 115200
python amsky01_viewer.py --port /dev/ttyACM0 --debug  # with communication output
```

**Dependencies:** `pyserial`, `numpy`, `pyqtgraph`, `PyQt5`

---

### `amsky01_cli.py`
CLI viewer with curses interface + automatic CSV logging:
- Real-time sensor data display in terminal
- Automatic data saving to CSV files
- Log file rotation every 10 minutes

**Usage:**
```bash
python amsky01_cli.py --port /dev/ttyACM0 --baud 115200
```

**Dependencies:** `pyserial`, `curses`

---

## Log Analysis Tools

### `plot_logs.py`
Plot graphs from saved CSV logs:
- Support for multiple files simultaneously
- Interactive mode with auto-refresh
- Export to PNG

**Usage:**
```bash
python plot_logs.py sensor_logs/latest.csv
python plot_logs.py --interactive --refresh 30 sensor_logs/*.csv
python plot_logs.py --output myplot.png sensor_logs/data.csv
```

**Dependencies:** `pandas`, `matplotlib`, `numpy`

---

### `plot_latest.sh`
Bash wrapper for quick log plotting:
```bash
./plot_latest.sh              # Plot latest log
./plot_latest.sh --all        # Plot all logs
./plot_latest.sh specific.csv # Plot specific file
```

---

## UART Message Format

Device communicates via UART at 115200 baud (configurable). Messages:

- `$thrmap,<192 values>` - IR thermal map (12×16 pixels)
- `$cloud,<TL>,<TR>,<BL>,<BR>,<CENTER>` - Corners and center of IR map
- `$cloud_meta,<Vdd>,<Ta>` - Voltage and temperature of MLX90641
- `$hygro,<temp>,<humidity>,<dew_point>` - Temperature, humidity, dew point
- `$light,<lux>,<full>,<ir>,<gain>,<int_time>,<sqm>` - Light and SQM

---

## Installing Dependencies

```bash
pip install pyserial numpy pyqtgraph PyQt5 pandas matplotlib
```
