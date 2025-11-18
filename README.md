# AMSKY01: Sky Quality & Cloud Detection Sensor

<p align="center">
  <img width="200" height="200" alt="AstroMeters Logo" src="https://github.com/user-attachments/assets/2135c8e6-5789-47cd-ac9b-e2287eecc98f" />
</p>


[AMSKY01](https://astrometers.eu/products/AMSKY01/) is a specialized sensor for astronomers and observatories. It combines two essential measurements in one device:
- **Sky Quality Meter (SQM)** - measures sky brightness for light pollution assessment
- **Cloud Detector** - uses thermal IR sky temperature measurement to detect cloud coverage

With both USB (CDC serial) and RS485 interfaces, AMSKY01 integrates easily into observatory automation systems, building management systems, or connects directly to computers for monitoring and data logging.

**Product page:** https://astrometers.eu/products/AMSKY01/  
**Documentation:** https://astrometers.eu/docs/AMSKY01/

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

## Where to Get It

To purchase AMSKY01 or for more information, contact us at **info@astrometers.eu**

## Communication Protocol

AMSKY01 outputs data via USB CDC serial at 115200 baud in CSV format. All data messages start with `$` prefix. Lines starting with `#` are comments/debug messages for human readability and should be ignored by parsing software.

### Startup Messages

```
# AMSKY01A
# Serial Number: <serial_number>
# FW Version: <version>
# Git Hash: <hash>
# Git Branch: <branch>
#
$HELLO,AMSKY01A,<serial_number>,<fw_version>,<git_hash>,<git_branch>
```

The `$HELLO` message contains structured device identification for automated parsing:
- `serial_number` - Unique 16-character hex ID from RP2040 chip (e.g., `E6614103E7452D2F`)

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
$hygro,<temperature>,<humidity>,<dew_point>
```
- `temperature` - Ambient temperature in °C
- `humidity` - Relative humidity in %
- `dew_point` - Dew point temperature in °C

**Cloud Sensor Metadata:**
```
$cloud_meta,<vdd>,<ta>
```
- `vdd` - Sensor supply voltage
- `ta` - Ambient temperature from thermal sensor

### Serial Commands

Send commands via serial (115200 baud) to configure the device:

**Thermal Map:**
- `thrmap_on` - Enable full 16×12 thermal map output
- `thrmap_off` - Disable thermal map output

When enabled, device outputs:
```
$thrmap,<pixel0>,<pixel1>,...,<pixel191>
```
192 temperature values in °C (16×12 array)

**Configuration:**

Configuration is stored persistently in EEPROM and survives power cycles.

- `config_show` - Display current configuration
- `config_save` - Save current configuration to EEPROM
- `config_reset` - Reset configuration to factory defaults

**SQM Calibration:**
- `set sqm_offset <value>` - Set SQM calibration offset (default: 8.5265)
  - This value combines the standard mag zeropoint (12.58) and solid angle correction for the 10° FOV lens
  - Adjust this value to calibrate against a reference SQM meter
  - The calculation uses fixed Pogson's ratio (-2.5) from the magnitude scale

**Alert Configuration:**

The device has a hardware alert output (GPIO 27) that can trigger on cloud detection and/or light levels.

- `set alert_enabled <0|1>` - Enable (1) or disable (0) alert output
- `set alert_cloud_temp <value>` - Cloud temperature threshold in °C (default: -10.0)
- `set alert_cloud_below <0|1>` - Alert when temp < threshold (1) or > threshold (0)
- `set alert_light_lux <value>` - Light threshold in lux (default: 10.0)
- `set alert_light_above <0|1>` - Alert when light > threshold (1) or < threshold (0)

**Device Settings:**
- `set device_label <text>` - Set custom device label/location (max 31 chars)

**Example Usage:**
```
set alert_enabled 1
set alert_cloud_temp -15.0
set alert_cloud_below 1
config_save
```
This enables alerts when sky temperature drops below -15°C (indicating clouds).

## Firmware

Pre-built firmware binaries are available:
- **Stable releases**: [Releases page](../../releases)
- **Development builds**: [Actions tab](../../actions)

Firmware files:
- `*.uf2` - For flashing via USB bootloader (drag & drop)
- `*.bin` - Binary for advanced flashing methods
- `*.elf` - Debug symbols
