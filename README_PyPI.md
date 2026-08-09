# AMSKY — Host software for AstroMeters sky quality & cloud sensors

<p align="center">
  <img width="200" height="200" alt="AstroMeters Logo" src="https://github.com/user-attachments/assets/2135c8e6-5789-47cd-ac9b-e2287eecc98f" />
</p>

Python host-side tools for the [AstroMeters](https://astrometers.eu/products/AMSKY02/) AMSKY
all-sky sensors: a real-time GUI viewer, a headless logger, a terminal UI client, and a
log plotting tool.

**This release supports the AMSKY02 protocol.**

The sensor combines two measurements that matter to astronomers and observatories:

- **Sky Quality Meter (SQM)** — sky brightness in mag/arcsec², for light pollution assessment
- **Cloud detection** — thermal IR sky temperature, for fast and reliable cloud coverage detection

The device streams CSV-style lines over USB CDC serial (115200 baud) or RS485. This
package parses that stream, visualises it, serves it over HTTP, and archives it to
HDF5 or CSV.

> **Using the older AMSKY01?** Its protocol differs (no sensor/channel index, 16×12
> thermal map) and is not handled by this release. Install
> [`amsky01`](https://pypi.org/project/amsky01/) instead.

- **Product page:** https://astrometers.eu/products/AMSKY02/
- **Documentation:** https://astrometers.eu/docs/AMSKY/
- **Source:** https://github.com/roman-dvorak/AMSKY02

---

## Installation

### Recommended: into a virtual environment

A virtual environment keeps the fairly heavy dependency set (PySide6 alone is a few
hundred MB) out of your system Python. On Debian/Ubuntu and Raspberry Pi OS this is
also the only way that works without `--break-system-packages`, because those systems
mark the system Python as externally managed (PEP 668).

```bash
# Debian/Ubuntu/Raspberry Pi OS: the venv module is a separate package
sudo apt install python3-venv

python3 -m venv ~/amsky-venv
source ~/amsky-venv/bin/activate
pip install --upgrade pip
pip install amsky
```

The commands are then on your `PATH` for as long as the environment is active:

```bash
amsky-viewer --port /dev/ttyACM0
deactivate                          # leave the environment
```

To run without activating — handy in cron, systemd units or scripts — call the
executable directly:

```bash
~/amsky-venv/bin/amsky-viewer --port /dev/ttyACM0 --headless --log
```

Upgrading later:

```bash
~/amsky-venv/bin/pip install --upgrade amsky
```

To remove everything, delete the directory: `rm -rf ~/amsky-venv`.

### Alternative: pipx

If you only want the command-line tools and never plan to import the modules, `pipx`
manages the virtual environment for you:

```bash
pipx install amsky
```

### Plain pip

```bash
pip install amsky
```

Works on systems whose Python is not externally managed, and inside an already active
virtual environment.

### Dependencies

Installing pulls in PySide6, pyqtgraph, numpy, pandas, matplotlib, h5py, pyserial and
psutil. The Qt dependency is large, but the viewer runs fine with `--headless` and no
display attached — useful on a small machine such as a Raspberry Pi in an observatory.

### Development builds

Every push to `main` publishes a pre-release versioned `X.Y.Z.devYYYYMMDDHHMM`. Regular
installs never pick these up; ask for them explicitly:

```bash
pip install --pre --upgrade amsky
```

### Serial port permissions (Linux)

Your user needs access to the serial device. On most distributions:

```bash
sudo usermod -aG dialout $USER   # log out and back in
```

---

## Command-line tools

Installing the package provides three commands.

### `amsky-viewer` — real-time GUI viewer

The main application. Shows a live thermal map, sky quality, environmental data and
per-channel light readings, with optional HDF5 logging and an HTTP JSON API.

```bash
# Live view from a connected sensor
amsky-viewer --port /dev/ttyACM0

# Live view with HDF5 logging and the HTTP API enabled
amsky-viewer --port /dev/ttyACM0 --log --api

# Replay a recorded HDF5 session at 4x speed
amsky-viewer --replay session.h5 --replay-speed 4

# Headless logging on a machine with no display
amsky-viewer --port /dev/ttyACM0 --headless --log --verbose
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

### `amsky-cli` — terminal client

A curses-based terminal UI with automatic CSV logging and rotation. Also usable over
TCP instead of a serial port, which is handy when the sensor is exposed by a
serial-to-network bridge.

```bash
amsky-cli --list-ports                    # discover connected devices
amsky-cli --port /dev/ttyACM0 --log       # TUI with CSV logging
amsky-cli --tcp 4001 --host observatory   # read from a network bridge
amsky-cli --port /dev/ttyACM0 --no-tui    # plain line output, good for pipes
```

### `amsky-plot` — plot recorded CSV logs

```bash
amsky-plot data.csv                            # write amsky_plots.png
amsky-plot --interactive data.csv              # interactive window
amsky-plot -i -r 30 -o myplot.png data.csv     # interactive, refresh every 30 s
amsky-plot file1.csv file2.csv                 # combine several logs
```

---

## Hardware

| | |
| --- | --- |
| Thermal | 2× MLX90642, 32×24 pixels |
| Light / SQM | 2× TSL2591 behind a PCA9543A I²C multiplexer |
| Environment | SHT4x — temperature, humidity, dew point |
| Interfaces | USB-C (CDC serial) and RS485 |

The two TSL2591 channels are shown and logged separately as **LIGHT0** and **LIGHT1**,
and the two thermal sensors are displayed side by side as a single combined map.

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
[protocol documentation](https://astrometers.eu/docs/AMSKY/)
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
from amsky_viewer import parse_light, parse_cloud

channel, lux, full_raw, ir_raw, gain, itime, sqm = parse_light(
    "$light,0,12.34,1000,200,1,100,21.50"
)
sensor_id, tl, tr, bl, br, center = parse_cloud(
    "$cloud,1,-20.1,-20.2,-20.3,-20.4,-21.0"
)
```

Each parser returns `None` for a line it does not recognise or cannot parse, so they
are safe to apply to a raw serial stream.

---

## Author

**Roman Dvořák**, AstroMeters — info@astrometers.eu

To purchase AMSKY02, or for integration support, get in touch at **info@astrometers.eu**.

## License

MIT — see [LICENSE](https://github.com/roman-dvorak/AMSKY02/blob/main/LICENSE).
