# MLX90641 I2C Address Change Utility

This utility changes the I2C address of MLX90641 thermal sensor from default **0x33** to **0x35**.

## ⚠️ Important Warnings

1. **Only ONE MLX90641 sensor** should be connected to the I2C bus during this operation
2. The address change is **permanent** (written to EEPROM)
3. A **power cycle is required** after the address change for it to take effect
4. Make sure no other devices are using address 0x35 on the I2C bus

## Building the Utility

```bash
# Build using the special configuration
pio run -c platformio_change_addr.ini

# Upload to device
pio run -c platformio_change_addr.ini -t upload
```

## Usage

1. **Connect only ONE MLX90641 sensor** to the AMSKY01 board
2. Upload and run the address change utility
3. Open serial monitor at 115200 baud
4. The program will:
   - Check for sensor at old address (0x33)
   - Check for sensor at new address (0x35)
   - Write new address to EEPROM using broadcast (0x00)
   - Verify the write
5. **Power cycle the sensor** (remove and reconnect power)
6. The sensor will now respond at address **0x35**

## Expected Output

```
========================================
MLX90641 I2C Address Change Utility
========================================

WARNING: Only ONE MLX90641 sensor should be on the I2C bus!

I2C bus initialized

Checking for sensor at address 0x33... FOUND
Reading current EEPROM address register... 0x33
Checking for sensor at address 0x35... NOT FOUND

========================================
Starting address change procedure
========================================

Writing new address 0x35 to EEPROM...
  Broadcasting to address 0x0, register 0x240F, data 0x35
  Write completed
SUCCESS: Address written to EEPROM

========================================
IMPORTANT: Power cycle the sensor now!
========================================

After power cycle, the sensor will respond at address 0x35
```

## LED Indicators

- **3 blinks every 2 seconds**: Success - power cycle the sensor
- **10 rapid blinks every second**: Error - check connections

## Verification

After power cycle, you can verify the address change:

```bash
# Scan I2C bus
i2cdetect -y 1

# Or use the main firmware - it should detect the sensor at 0x35
```

## Reverting to Original Address

To change back to 0x33, modify `change_address_main.cpp`:

```cpp
#define MLX90641_OLD_ADDR 0x35         // Current address
#define MLX90641_NEW_ADDR 0x33         // Target address
```

Then rebuild and run the utility again.

## Technical Details

- **EEPROM Register**: 0x240F
- **Data Format**: Lower 7 bits contain the I2C address
- **Broadcast Address**: 0x00 (responds to all devices)
- **Write Time**: ~50ms for EEPROM write completion
- **Activation**: Requires power cycle

## Troubleshooting

### Sensor not found at 0x33
- Check I2C connections (SDA=GPIO18, SCL=GPIO19)
- Verify sensor power supply
- Check if sensor address was already changed

### Write verification failed
- This is usually OK - verification can fail when using broadcast address
- Proceed with power cycle if write succeeded

### Sensor still responds at old address after power cycle
- EEPROM write might have failed
- Try running the utility again
- Check for I2C bus errors in serial output

## References

- MLX90641 Datasheet: Section on I2C address configuration
- EEPROM address register: 0x240F
- Default factory address: 0x33
