/**
 * MLX90641 I2C Address Change Utility
 * 
 * This program changes the MLX90641 I2C address from 0x33 to 0x35
 * using the global broadcast address 0x00.
 * 
 * IMPORTANT: Only one MLX90641 sensor should be on the I2C bus during this operation!
 * 
 * Procedure:
 * 1. Write new address to EEPROM register 0x240F
 * 2. Verify the write
 * 3. Power cycle the sensor to activate new address
 */

#include <Arduino.h>
#include <Wire.h>

// Pin definitions from AMSKY01
#define SDA_PIN 18
#define SCL_PIN 19

// MLX90641 I2C addresses
#define MLX90641_BROADCAST_ADDR 0x00  // Global broadcast address
#define MLX90641_OLD_ADDR 0x33         // Current address
#define MLX90641_NEW_ADDR 0x35         // Target address

// MLX90641 EEPROM address register
#define MLX90641_EEPROM_ADDR_REG 0x240F

// Status LED
#define CPU_STATUS_LED 25

// Function prototypes
int writeEEPROMAddress(uint8_t slaveAddr, uint8_t newAddr);
int readEEPROMAddress(uint8_t slaveAddr);
void blinkLED(int times, int delayMs);
void scanI2C();

void setup() {
  Serial.begin(115200);
  delay(2000);
  
  pinMode(CPU_STATUS_LED, OUTPUT);
  digitalWrite(CPU_STATUS_LED, LOW);
  
  Serial.println("========================================");
  Serial.println("MLX90641 I2C Address Change Utility");
  Serial.println("========================================");
  Serial.println();
  Serial.println("WARNING: Only ONE MLX90641 sensor should be on the I2C bus!");
  Serial.println();
  
  // Initialize I2C
  Wire1.setSDA(SDA_PIN);
  Wire1.setSCL(SCL_PIN);
  Wire1.begin();
  Wire1.setClock(1000000); // 1 MHz
  delay(100);
  
  Serial.println("I2C bus initialized");
  Serial.println();
  
  // Scan I2C bus first
  Serial.println("Scanning I2C bus...");
  scanI2C();
  Serial.println();
  
  // Step 1: Check if sensor responds at old address
  Serial.print("Checking for sensor at address 0x");
  Serial.print(MLX90641_OLD_ADDR, HEX);
  Serial.print("... ");
  
  Wire1.beginTransmission(MLX90641_OLD_ADDR);
  uint8_t oldAddrError = Wire1.endTransmission();
  
  if (oldAddrError == 0) {
    Serial.println("FOUND");
    
    // Read current EEPROM address setting
    Serial.print("Reading current EEPROM address register (0x240F)... ");
    int currentAddr = readEEPROMAddress(MLX90641_OLD_ADDR);
    if (currentAddr >= 0) {
      Serial.print("raw value = 0x");
      Serial.print(currentAddr, HEX);
      Serial.print(" (I2C address would be 0x");
      Serial.print((currentAddr >> 1) & 0x7F, HEX);
      Serial.println(")");
    } else {
      Serial.println("FAILED");
    }
  } else {
    Serial.println("NOT FOUND");
  }
  
  // Step 2: Check if sensor already at new address
  Serial.print("Checking for sensor at address 0x");
  Serial.print(MLX90641_NEW_ADDR, HEX);
  Serial.print("... ");
  
  Wire1.beginTransmission(MLX90641_NEW_ADDR);
  uint8_t newAddrError = Wire1.endTransmission();
  
  if (newAddrError == 0) {
    Serial.println("FOUND - Sensor already at target address!");
    Serial.println();
    Serial.println("No change needed. Exiting.");
    blinkLED(5, 200);
    return;
  } else {
    Serial.println("NOT FOUND");
  }
  
  Serial.println();
  
  // Step 3: Write new address using OLD address (NOT broadcast!)
  // MLX90641 requires communication on current address, not broadcast
  Serial.println("========================================");
  Serial.println("Starting address change procedure");
  Serial.println("========================================");
  Serial.println();
  
  Serial.print("Writing new address 0x");
  Serial.print(MLX90641_NEW_ADDR, HEX);
  Serial.println(" to EEPROM...");
  
  // Check if sensor was found at old address
  if (oldAddrError != 0) {
    Serial.println();
    Serial.print("ERROR: Sensor not found at address 0x");
    Serial.print(MLX90641_OLD_ADDR, HEX);
    Serial.println("!");
    Serial.println("Cannot proceed with address change.");
    Serial.println();
    Serial.println("Please check:");
    Serial.println("  - I2C connections (SDA=GPIO18, SCL=GPIO19)");
    Serial.println("  - Sensor power supply");
    Serial.println("  - Only ONE MLX90641 on the bus");
    
    while (true) {
      blinkLED(10, 100);
      delay(1000);
    }
  }
  
  int result = writeEEPROMAddress(MLX90641_OLD_ADDR, MLX90641_NEW_ADDR);
  
  if (result == 0) {
    Serial.println("SUCCESS: Address written to EEPROM");
    Serial.println();
    Serial.println("========================================");
    Serial.println("IMPORTANT: Power cycle the sensor now!");
    Serial.println("========================================");
    Serial.println();
    Serial.println("After power cycle, the sensor will respond at address 0x35");
    
    // Blink LED to indicate success
    while (true) {
      blinkLED(3, 300);
      delay(2000);
    }
  } else {
    Serial.print("FAILED: Error code ");
    Serial.println(result);
    Serial.println();
    Serial.println("Please check connections and try again.");
    
    // Rapid blink to indicate error
    while (true) {
      blinkLED(10, 100);
      delay(1000);
    }
  }
}

void loop() {
  // Not used
}

/**
 * Write new I2C address to MLX90641 EEPROM
 * 
 * MLX90641 requires a specific procedure:
 * 1. Erase EEPROM cell by writing 0x0000
 * 2. Wait ≥5ms
 * 3. Write new address (7-bit address << 1)
 * 4. Wait ≥5ms
 * 5. Power cycle required for activation
 * 
 * @param slaveAddr Current I2C address (NOT broadcast 0x00)
 * @param newAddr New 7-bit I2C address to set
 * @return 0 on success, negative on error
 */
int writeEEPROMAddress(uint8_t slaveAddr, uint8_t newAddr) {
  // Step 1: Erase EEPROM cell by writing 0x0000
  Serial.println("  Step 1: Erasing EEPROM cell...");
  Serial.print("    Writing 0x0000 to address 0x");
  Serial.print(slaveAddr, HEX);
  Serial.print(", register 0x");
  Serial.println(MLX90641_EEPROM_ADDR_REG, HEX);
  
  Wire1.beginTransmission(slaveAddr);
  Wire1.write(MLX90641_EEPROM_ADDR_REG >> 8);   // High byte of register address
  Wire1.write(MLX90641_EEPROM_ADDR_REG & 0xFF); // Low byte of register address
  Wire1.write(0x00);                             // High byte: 0x00
  Wire1.write(0x00);                             // Low byte: 0x00
  
  uint8_t error = Wire1.endTransmission();
  
  if (error != 0) {
    Serial.print("    Erase failed with I2C error: ");
    Serial.println(error);
    return -1;
  }
  
  Serial.println("    Erase completed");
  delay(10);  // Wait ≥5ms for EEPROM erase
  
  // Step 2: Write new address directly (no shift)
  // Write 0x35 directly
  uint16_t addrData = newAddr & 0x7F;
  
  Serial.println("  Step 2: Writing new address...");
  Serial.print("    Writing 0x");
  Serial.print(addrData, HEX);
  Serial.print(" to address 0x");
  Serial.print(slaveAddr, HEX);
  Serial.print(", register 0x");
  Serial.println(MLX90641_EEPROM_ADDR_REG, HEX);
  
  Wire1.beginTransmission(slaveAddr);
  Wire1.write(MLX90641_EEPROM_ADDR_REG >> 8);   // High byte of register address
  Wire1.write(MLX90641_EEPROM_ADDR_REG & 0xFF); // Low byte of register address
  Wire1.write(addrData >> 8);                    // High byte of data (should be 0x00)
  Wire1.write(addrData & 0xFF);                  // Low byte of data
  
  error = Wire1.endTransmission();
  
  if (error != 0) {
    Serial.print("    Write failed with I2C error: ");
    Serial.println(error);
    return -2;
  }
  
  Serial.println("    Write completed");
  delay(10);  // Wait ≥5ms for EEPROM write
  
  // Step 3: Verify by reading back
  Serial.print("  Step 3: Verifying write... ");
  int readBack = readEEPROMAddress(slaveAddr);
  
  if (readBack == addrData) {
    Serial.print("VERIFIED (read 0x");
    Serial.print(readBack, HEX);
    Serial.println(")");
    return 0;
  } else if (readBack >= 0) {
    Serial.print("MISMATCH (expected 0x");
    Serial.print(addrData, HEX);
    Serial.print(", read 0x");
    Serial.print(readBack, HEX);
    Serial.println(")");
    return -3;
  } else {
    Serial.println("READ FAILED (but write may have succeeded)");
    // Still return success if write succeeded
    return 0;
  }
}

/**
 * Read current I2C address from MLX90641 EEPROM
 * 
 * @param slaveAddr Current I2C address
 * @return Address value (0-127) on success, negative on error
 */
int readEEPROMAddress(uint8_t slaveAddr) {
  Wire1.beginTransmission(slaveAddr);
  Wire1.write(MLX90641_EEPROM_ADDR_REG >> 8);
  Wire1.write(MLX90641_EEPROM_ADDR_REG & 0xFF);
  
  if (Wire1.endTransmission(false) != 0) {
    return -1;
  }
  
  if (Wire1.requestFrom(slaveAddr, (uint8_t)2) != 2) {
    return -2;
  }
  
  uint8_t hi = Wire1.read();
  uint8_t lo = Wire1.read();
  
  uint16_t addrData = (hi << 8) | lo;
  return addrData & 0x7F; // Return only the 7-bit address
}

/**
 * Blink status LED
 */
void blinkLED(int times, int delayMs) {
  for (int i = 0; i < times; i++) {
    digitalWrite(CPU_STATUS_LED, HIGH);
    delay(delayMs);
    digitalWrite(CPU_STATUS_LED, LOW);
    delay(delayMs);
  }
}

/**
 * Scan I2C bus for all devices
 */
void scanI2C() {
  uint8_t error, address;
  int nDevices = 0;
  
  Serial.println("  Scanning addresses 0x03 to 0x77...");
  
  for(address = 3; address < 128; address++) {
    Wire1.beginTransmission(address);
    error = Wire1.endTransmission();
    
    if (error == 0) {
      Serial.print("  Device found at address 0x");
      if (address < 16) Serial.print("0");
      Serial.println(address, HEX);
      nDevices++;
    }
  }
  
  if (nDevices == 0) {
    Serial.println("  No I2C devices found!");
  } else {
    Serial.print("  Found ");
    Serial.print(nDevices);
    Serial.println(" device(s)");
  }
}
