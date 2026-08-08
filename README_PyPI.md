# AMSKY01 — Host software for AstroMeters sky quality & cloud sensors

<p align="center">
  <img width="200" height="200" alt="AstroMeters Logo" src="https://github.com/user-attachments/assets/2135c8e6-5789-47cd-ac9b-e2287eecc98f" />
</p>

Python host-side tools for the [AstroMeters](https://astrometers.eu) all-sky sensors:
a real-time GUI viewer, a headless logger, a terminal UI client, and a log plotting
tool.

**This release (1.1.0) targets the AMSKY02B protocol.** For AMSKY01A/B hardware, see
[Supported hardware](#supported-hardware) below.

These sensors combine two measurements that matter to astronomers and observatories:

- **Sky Quality Meter (SQM)** — sky brightness in mag/arcsec², for light pollution assessment
- **Cloud detection** — thermal IR sky temperature, for fast and reliable cloud coverage detection

The device streams CSV-style lines over USB CDC serial (115200 baud) or RS485. This
package parses that stream, visualises it, serves it over HTTP, and archives it to
HDF5 or CSV.

**Product page:** https://astrometers.eu/products/AMSKY01/
**Documentation:** https://astrometers.eu/docs/AMSKY01/
**Source:** https://github.com/AstroMeters/AMSKY01

---

## Installation

```bash
pip install amsky01
```

This pulls in PySide6, pyqtgraph, numpy, pandas, matplotlib, h5py, pyserial and psutil.

If you only need headless logging on a small machine (e.g. a Raspberry Pi in an
observatory), install into a virtual environment — the Qt dependency is large but the
viewer runs fine with `--headless` and no display attached.

### Serial port permissions (Linux)

Your user needs access to the serial device. On most distributions:

```bash
sudo usermod -aG dialout $USER   # log out and back in
```

---

## Command-line tools

Installing the package provides three commands.

### `amsky01-viewer` — real-time GUI viewer

The main application. Shows a live thermal map, sky quality, environmental data and
per-channel light readings, with optional HDF5 logging and an HTTP JSON API.

```bash
# Live view from a connected sensor
amsky01-viewer --port /dev/ttyACM0

# Live view with HDF5 logging and the HTTP API enabled
amsky01-viewer --port /dev/ttyACM0 --log --api

# Replay a recorded HDF5 session at 4x speed
amsky01-viewer --replay AMSKY01_20260502_18.h5 --replay-speed 4

# Headless logging on a machine with no display
amsky01-viewer --port /dev/ttyACM0 --headless --log --verbose
```

| Option | Description |
| --- | --- |
| `--port PORT` | Serial port, e.g. `/dev/ttyACM0` |
| `--baud BAUD` | Baud rate (default 115200) |
| `--replay FILE` | Replay a recorded HDF5 log instead of reading a port |
| `--replay-speed N` | Replay speed multiplier (default 1.0) |
| `--vmin` / `--vmax` | Temperature limits for the thermal colour scale |
| `--rotation DEG` | Rotate the thermal image |
| `--log` | Enable HDF5 logging at startup |
| `--log-name ID` | Device ID used in HDF5 filenames |
| `--log-path PATH` | Directory for HDF5 files |
| `--api` | Enable the HTTP JSON API at startup |
| `--sqm-zp VALUE` | SQM calibration zero point (default 24.0) |
| `--headless`, `--no-gui` | Run without a GUI — parse and log only |
| `--verbose`, `-v` | Print received values to stdout |
| `--stats-interval S` | Status summary interval in headless mode |
| `--debug` | Show every message received on the serial line |

### `amsky01-cli` — terminal client

A curses-based terminal UI with automatic CSV logging and rotation. Also usable over
TCP instead of a serial port, which is handy when the sensor is exposed by a serial-to-
network bridge.

```bash
amsky01-cli --list-ports                    # discover connected devices
amsky01-cli --port /dev/ttyACM0 --log       # TUI with CSV logging
amsky01-cli --tcp 4001 --host observatory   # read from a network bridge
amsky01-cli --port /dev/ttyACM0 --no-tui    # plain line output, good for pipes
```

### `amsky01-plot` — plot recorded CSV logs

```bash
amsky01-plot data.csv                            # write amsky01_plots.png
amsky01-plot --interactive data.csv              # interactive window
amsky01-plot -i -r 30 -o myplot.png data.csv     # interactive, refresh every 30 s
amsky01-plot file1.csv file2.csv                 # combine several logs
```

---

## Supported hardware

| Model | Thermal sensor | Light sensors | Supported by this release |
| --- | --- | --- | --- |
| AMSKY02B | MLX90642, 32×24 | 2× TSL2591 behind a PCA9543A I²C mux | Yes |
| AMSKY01A / AMSKY01B | MLX90641, 16×12 | 1× TSL2591 | No — use `amsky01==1.0.0` |

> **Important:** this release targets the **AMSKY02B** protocol, in which every data
> message carries a leading sensor/channel index and the thermal map is 32×24. The
> resolution is fixed, not auto-detected. The older AMSKY01A/B protocol — no index
> field, 16×12 map — is **not** parsed by this version. If you have an AMSKY01A/B,
> pin the previous release:
>
> ```bash
> pip install "amsky01==1.0.0"
> ```

On AMSKY02B the two TSL2591 channels are shown and logged separately as **LIGHT0**
and **LIGHT1**, and the two thermal sensors are displayed side by side.

Environmental data comes from an SHT4x (temperature, humidity, dew point).

---

## Serial protocol

All data lines start with `$`. Lines starting with `#` are human-readable comments and
should be ignored by parsers.

```
$HELLO,<model>,<serial>,<fw_version>,<git_hash>,<git_branch>
$light,<channel>,<lux>,<full_raw>,<ir_raw>,<gain>,<int_time>,<sqm>
$cloud,<sensor_id>,<tl>,<tr>,<bl>,<br>,<center>
$cloud_meta,<sensor_id>,<vdd>,<ta>
$hygro,<temperature>,<humidity>,<dew_point>
$thrmap,<sensor_id>,<pixel0>,...,<pixel767>
```

Notes:

- `$light` carries a leading **channel number** (0 or 1) identifying which TSL2591
  behind the I²C mux produced the reading.
- `$cloud` and `$cloud_meta` carry a leading **sensor_id** selecting one of the two
  MLX90642 thermal sensors.
- `$cloud` gives the four corner temperatures and the centre sky temperature in °C.
- `$thrmap` is the full 32×24 thermal map — 768 values, enabled with the `thrmap_on`
  serial command.
- `$hygro` is the only message with no index field.

Device configuration is stored in EEPROM and survives power cycles. See the
[protocol documentation](https://github.com/AstroMeters/AMSKY01#communication-protocol)
for the full command set, including SQM calibration and the hardware alert output.

---

## HDF5 logging

With `--log`, the viewer writes a self-describing HDF5 file containing resizable,
timestamped datasets grouped per subsystem:

```
/sky<N>/       thermal map frames, timestamps, sensor temperature
/cloud<N>/     corner and centre temperatures
/light<C>/     full-spectrum, IR, gain, integration time per channel
/hygro/        temperature, humidity
```

Files are named from `--log-name` and the session start time, and can be replayed later
with `--replay`.

---

## HTTP JSON API

With `--api`, the viewer serves the most recent readings as JSON:

```bash
curl http://localhost:8080/data.json
```

Port 8080 is the default; it is configurable in the viewer's settings panel and is
remembered between runs.

This makes it straightforward to feed an observatory dashboard, a weather-safety
watchdog, or a home automation system without parsing the serial stream yourself.

---

## Using the parsers from your own code

The modules are importable, so you can reuse the protocol parsing directly:

```python
from amsky01_viewer import parse_light

channel, lux, full_raw, ir_raw, gain, itime, sqm = parse_light(
    "$light,0,12.34,1000,200,1,100,21.50"
)
```

---

## Author

**Roman Dvořák**, AstroMeters — info@astrometers.eu

To purchase AMSKY01 or AMSKY02B, or for integration support, get in touch at
**info@astrometers.eu**.

## License

MIT — see [LICENSE](https://github.com/AstroMeters/AMSKY01/blob/main/LICENSE).
