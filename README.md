# AMSKY01

Sky Quality & Cloud Detection Sensor

AMSKY01 is a specialized sensor for astronomers and observatories. It combines two essential measurements in one device:
- **Sky Quality Meter (SQM)** - measures sky brightness for light pollution assessment
- **Cloud Detector** - uses thermal IR sky temperature measurement to detect cloud coverage

With both USB (CDC serial) and RS485 interfaces, AMSKY01 integrates easily into observatory automation systems, building management systems, or connects directly to computers for monitoring and data logging.

## Key Features

* **Sky Quality Measurement (SQM)** - Real-time readings in magnitudes per square arcsecond (mag/arcsec²) for objective sky brightness assessment
* **Cloud Coverage Detection** - Thermal IR sky temperature sensor for fast and reliable cloud detection
* **Dual Interface** - USB-C (CDC serial) and RS485 for flexible connectivity
* **Open Protocol** - Documented protocol for custom integration and automation
* **Weatherproof Design** - Rugged enclosure for permanent outdoor installations

## Applications

* Light pollution monitoring and sky quality documentation
* Automated cloud detection for remote and robotic observatories  
* Integration into observatory automation and building management systems via RS485
* Sky monitoring networks for astronomy research
* Citizen science projects

## Communication Protocol

AMSKY01 outputs data via USB CDC serial at 115200 baud in CSV format. All data messages start with `$` prefix.

### Startup Messages

```
# AMSKY01A
# FW Version: <version>
# Git Hash: <hash>
# Git Branch: <branch>
#
$HELO,AMSKY01A,<fw_version>,<git_hash>,<git_branch>
```

### Data Output (every 2 seconds)

**Sky Quality (SQM) Data:**
```
$light,<lux>,<full_raw>,<ir_raw>,<gain>,<integration_time>,<sqm>
```
- `lux` - Normalized lux value (2 decimal places)
- `full_raw` - Raw full spectrum sensor reading
- `ir_raw` - Raw infrared sensor reading
- `gain` - Current sensor gain setting
- `integration_time` - Current integration time
- `sqm` - Sky quality in mag/arcsec² (2 decimal places)

**Cloud Detection Data:**
```
$cloud,<tl>,<tr>,<bl>,<br>,<center>
```
- `tl`, `tr`, `bl`, `br` - Corner temperatures in °C (top-left, top-right, bottom-left, bottom-right)
- `center` - Center sky temperature in °C

**Environmental Data:**
```
$hygro,<temperature>,<humidity>
```
- `temperature` - Ambient temperature in °C
- `humidity` - Relative humidity in %

**Thermal Parameters:**
```
$thr_parameters,<vdd>,<ta>
```
- `vdd` - Sensor supply voltage
- `ta` - Ambient temperature from thermal sensor

### Optional Commands

Send via serial to enable/disable thermal map streaming:
- `thrmap_on` - Enable full 16×12 thermal map output
- `thrmap_off` - Disable thermal map output

When enabled, device outputs:
```
$thrmap,<pixel0>,<pixel1>,...,<pixel191>
```
192 temperature values in °C (16×12 array)

## Firmware

Pre-built firmware binaries are available:
- **Stable releases**: [Releases page](../../releases)
- **Development builds**: [Actions tab](../../actions)

Firmware files:
- `*.uf2` - For flashing via USB bootloader (drag & drop)
- `*.bin` - Binary for advanced flashing methods
- `*.elf` - Debug symbols
