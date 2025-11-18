# AMSKY01

Sky Quality & Cloud Detection Sensor

AMSKY01 is a specialized sensor for astronomers and observatories. It measures sky brightness and detects cloud coverage using advanced sky temperature measurement.
With both USB (CDC serial) and RS485 interfaces, AMSKY01 can be easily connected to computers, automation controllers, or building management systems. Designed for permanent installations, AMSKY01 delivers essential data for night sky observation, light pollution monitoring, and observatory automation — in a single, robust device.

### Key Features

 * Sky Quality Measurement (SQM) Real-time readings in magnitudes per square arcsecond (mag/arcsec²) for objective light pollution assessment.
 * Cloud Coverage Detection Dedicated sky temperature sensor (thermal IR) for fast cloud presence and sky clarity evaluation.
 * Dual Interface: USB & RS485 Plug-and-play via USB-C (CDC serial) for computers, or RS485 for direct integration with observatory or building automation systems (BMS/SCADA).
 * Open Protocol & API Fully documented for custom integration and automation.
 * Weatherproof & Durable Rugged enclosure for outdoor and permanent installations.

### Typical Applications
 * Monitoring and documenting light pollution and sky quality (SQM).
 * Automated cloud detection for remote or robotic observatories.
 * Integration into building management and dome automation systems via RS485.
 * Sky monitoring for astronomy networks.
 * Citizen science and research projects.

## Firmware

### Building

The firmware is built using PlatformIO:

```bash
cd fw
pio run
```

### CI/CD

Firmware is automatically built on every commit using GitHub Actions:
- **Development builds**: Artifacts are available in the Actions tab with naming `AMSKY01-firmware-dev_build-<commit-hash>`
- **Release builds**: Firmware binaries are automatically attached to GitHub releases

### Downloading Pre-built Firmware

- **Latest development build**: Check the [Actions tab](../../actions) for the most recent successful build
- **Stable releases**: Download from the [Releases page](../../releases)

Firmware files:
- `*.uf2` - Flash by copying to Pico in bootloader mode
- `*.bin` - Binary for advanced flashing methods
- `*.elf` - Debug symbols
