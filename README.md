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

## Firmware

Pre-built firmware binaries are available:
- **Stable releases**: [Releases page](../../releases)
- **Development builds**: [Actions tab](../../actions)

Firmware files:
- `*.uf2` - For flashing via USB bootloader (drag & drop)
- `*.bin` - Binary for advanced flashing methods
- `*.elf` - Debug symbols
