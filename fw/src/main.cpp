#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_SHT4x.h>
#include "AMS_TSL2591.h"
#include "MLX90641.h"
#include "version.h"
#include "sqm_utils.h"
#include "amsky01_utils.h"
#include "config.h"

// RP2040 bootloader reset function
extern "C" {
  void reset_usb_boot(uint32_t usb_activity_gpio_mask, uint32_t disable_interface_mask);
}

// Firmware and hardware version info
#define DEVICE_NAME "AMSKY01A"
#define FW_VERSION BUILD_VERSION

// Pin definitions
#define CPU_STATUS_LED 22   // CPU status LED
#define TRIGGER_OUT_LED 27  // Trigger out LED
#define SDA_PIN 18   // I2C1 SDA
#define SCL_PIN 19   // I2C1 SCL

// Initialize SHT45 sensor
Adafruit_SHT4x sht4 = Adafruit_SHT4x();

// Initialize AMS TSL2591 light sensor
AMS_TSL2591 amsSensor;

// Initialize MLX90641 thermal sensor
MLX90641 mlxSensor;

// Initialize configuration manager
ConfigManager configManager;

// Variables for LEDs
bool trigger_led_state = false;
unsigned long last_trigger_blink = 0;
const unsigned long TRIGGER_BLINK_INTERVAL = 1000; // 1000ms - slower blink

// CPU LED PWM breathing effect
const unsigned long CPU_BREATHING_PERIOD = 2000; // 2 seconds for full cycle
const float MY_PI = 3.14159265359;

// Variables for sensors
bool sht4_available = false;
bool tsl_available = false;
unsigned long last_measurement = 0;
const unsigned long MEASUREMENT_INTERVAL = 2000; // 2 seconds

// Režim posílání celé IR mapy po UARTu
bool thrmap_streaming = false;

// Enter UF2 bootloader mode
static void enterUf2Bootloader() {
  Serial.println("# Entering UF2 bootloader mode...");
  Serial.flush();
  delay(100);
  reset_usb_boot(0, 0);  // Reset to UF2 bootloader in ROM
}

static void processSerialCommand(const char *cmd)
{
  if (strcmp(cmd, "thrmap_on") == 0)
  {
    thrmap_streaming = true;
    Serial.println("# thrmap streaming ON");
  }
  else if (strcmp(cmd, "thrmap_off") == 0)
  {
    thrmap_streaming = false;
    Serial.println("# thrmap streaming OFF");
  }
  else if (strcmp(cmd, "config_show") == 0)
  {
    configManager.printConfig();
  }
  else if (strcmp(cmd, "config_save") == 0)
  {
    configManager.save();
  }
  else if (strcmp(cmd, "config_reset") == 0)
  {
    configManager.reset();
  }
  else if (strcmp(cmd, "bootloader") == 0)
  {
    enterUf2Bootloader();
  }
  else if (strncmp(cmd, "set ", 4) == 0)
  {
    // Parse "set <param> <value>" commands
    const char* params = cmd + 4;
    char param[32];
    char value[32];
    
    if (sscanf(params, "%s %s", param, value) == 2)
    {
      if (strcmp(param, "sqm_offset") == 0) {
        configManager.setSqmOffset(atof(value));
        Serial.print("# Set sqm_offset = "); Serial.println(value);
      }
      else if (strcmp(param, "alert_enabled") == 0) {
        configManager.setAlertEnabled(atoi(value));
        Serial.print("# Set alert_enabled = "); Serial.println(value);
      }
      else if (strcmp(param, "alert_cloud_temp") == 0) {
        configManager.setAlertCloudTempThreshold(atof(value));
        Serial.print("# Set alert_cloud_temp = "); Serial.println(value);
      }
      else if (strcmp(param, "alert_cloud_below") == 0) {
        configManager.setAlertCloudBelow(atoi(value));
        Serial.print("# Set alert_cloud_below = "); Serial.println(value);
      }
      else if (strcmp(param, "alert_light_lux") == 0) {
        configManager.setAlertLightThreshold(atof(value));
        Serial.print("# Set alert_light_lux = "); Serial.println(value);
      }
      else if (strcmp(param, "alert_light_above") == 0) {
        configManager.setAlertLightAbove(atoi(value));
        Serial.print("# Set alert_light_above = "); Serial.println(value);
      }
      else if (strcmp(param, "device_label") == 0) {
        configManager.setDeviceLabel(value);
        Serial.print("# Set device_label = "); Serial.println(value);
      }
      else {
        Serial.print("# Unknown parameter: "); Serial.println(param);
      }
    }
    else {
      Serial.println("# Invalid set command format. Use: set <param> <value>");
    }
  }
  else
  {
    Serial.print("# Unknown command: "); Serial.println(cmd);
  }
}

static void handleSerialCommands()
{
  static char buf[64];
  static uint8_t pos = 0;

  while (Serial.available() > 0)
  {
    char c = Serial.read();
    if (c == '\n' || c == '\r')
    {
      if (pos > 0)
      {
        buf[pos] = '\0';
        processSerialCommand(buf);
        pos = 0;
      }
    }
    else if (pos < sizeof(buf) - 1)
    {
      buf[pos++] = c;
    }
  }
}

void setup() {
  // Initialize serial communication
  Serial.begin(115200);
  delay(2000);
  
  // Initialize GPIO pins
  pinMode(CPU_STATUS_LED, OUTPUT);
  pinMode(TRIGGER_OUT_LED, OUTPUT);
  
  // LEDs off at start
  digitalWrite(CPU_STATUS_LED, LOW);
  digitalWrite(TRIGGER_OUT_LED, LOW);
  
  // Get device serial number
  String serial_number = getDeviceSerialNumber();
  
  // Print device information
  Serial.print("# ");
  Serial.println(DEVICE_NAME);
  Serial.print("# Serial Number: ");
  Serial.println(serial_number);
  Serial.print("# FW Version: ");
  Serial.println(FW_VERSION);
  Serial.print("# Git Hash: ");
  Serial.println(GIT_HASH);
  Serial.print("# Git Branch: ");
  Serial.println(GIT_BRANCH);
  Serial.println("#");
  
  // Send structured HELLO message with device identification
  // Format: $HELLO,<device_name>,<serial_number>,<fw_version>,<git_hash>,<git_branch>
  Serial.print("$HELLO,");
  Serial.print(DEVICE_NAME);
  Serial.print(",");
  Serial.print(serial_number);
  Serial.print(",");
  Serial.print(FW_VERSION);
  Serial.print(",");
  Serial.print(GIT_HASH);
  Serial.print(",");
  Serial.print(GIT_BRANCH);
  Serial.println();
  
  // Initialize I2C1 with specific pins (GPIO 18=SDA, GPIO 19=SCL)
  Wire1.setSDA(SDA_PIN);
  Wire1.setSCL(SCL_PIN);
  Wire1.begin();
  delay(100);
  
  // Initialize SHT45 sensor on I2C1
  if (sht4.begin(&Wire1)) {
    sht4_available = true;
    
    // Set precision and heater
    sht4.setPrecision(SHT4X_HIGH_PRECISION);
    sht4.setHeater(SHT4X_NO_HEATER);
    Serial.println("# SHT4x sensor initialized successfully");
  } else {
    sht4_available = false;
    Serial.println("# SHT4x sensor initialization failed");
  }
  
  // Initialize AMS TSL2591 light sensor on I2C1
  if (amsSensor.begin(&Wire1)) {
    tsl_available = true;
  } else {
    tsl_available = false;
  }
  
  // Initialize MLX90641 thermal sensor on I2C1
  if (mlxSensor.begin(&Wire1)) {
    // MLX sensor is available
  } else {
    // MLX sensor is not available
  }
  
  // Initialize configuration manager
  configManager.begin();
  configManager.printConfig();
}

void loop() {
  // Zpracuj případné příkazy z UARTu (thrmap_on/thrmap_off)
  handleSerialCommands();

  // Handle CPU status LED PWM breathing effect
  unsigned long current_time = millis();
  float phase = (current_time % CPU_BREATHING_PERIOD) / (float)CPU_BREATHING_PERIOD;
  float sine_wave = sin(phase * 2 * MY_PI);
  
  // Convert sine wave (-1 to 1) to PWM duty cycle (0 to 64) - reduced brightness
  // Use absolute value to make it always positive, then scale to 25% of original brightness
  int pwm_value = (int)(32 + 32 * sine_wave);
  
  analogWrite(CPU_STATUS_LED, pwm_value);
  
  // Handle trigger out LED blinking (1000ms)
  if (current_time - last_trigger_blink >= TRIGGER_BLINK_INTERVAL) {
    trigger_led_state = !trigger_led_state;
    digitalWrite(TRIGGER_OUT_LED, trigger_led_state);
    last_trigger_blink = current_time;
  }
  
// Read sensor data every 2 seconds
  if ((sht4_available || tsl_available || mlxSensor.isAvailable()) && (current_time - last_measurement >= MEASUREMENT_INTERVAL)) {
    if (sht4_available) {
      sensors_event_t humidity, temp;
      
      if (sht4.getEvent(&humidity, &temp)) {
        // Calculate dew point using Magnus formula
        // Td = (b * alpha) / (a - alpha)
        // where alpha = (a * T) / (b + T) + ln(RH/100)
        // a = 17.27, b = 237.7 for temperatures above 0°C
        float T = temp.temperature;
        float RH = humidity.relative_humidity;
        const float a = 17.27;
        const float b = 237.7;
        float alpha = ((a * T) / (b + T)) + log(RH / 100.0);
        float dew_point = (b * alpha) / (a - alpha);
        
        // Output in CSV format: hygro,<temp>,<humid>,<dew_point>
        Serial.print("$hygro,");
        Serial.print(temp.temperature, 2);
        Serial.print(",");
        Serial.print(humidity.relative_humidity, 2);
        Serial.print(",");
        Serial.print(dew_point, 2);
        Serial.println();
      } else {
        Serial.println("$hygro,-999,-999,-999");
      }
    }
    
    if (tsl_available && amsSensor.isAvailable()) {
      float normalized_lux;
      uint16_t full_raw, ir_raw;
      const char* gain_str;
      const char* integration_time_str;
      
      if (amsSensor.readLightData(normalized_lux, full_raw, ir_raw, gain_str, integration_time_str)) {
        // Convert normalized_lux to double for SQM calculation
        double lux_double = (double)normalized_lux;
        double sqm_value = convert_lux_to_sqm(lux_double);
        
        // Output in CSV format: light,normalized_lux,full_raw,ir_raw,gain,integration_time,sqm
        Serial.print("$light,");
        Serial.print(normalized_lux, 2);  // Normalized lux value with 2 decimal places
        Serial.print(",");
        Serial.print(full_raw);    // Raw full spectrum value
        Serial.print(",");
        Serial.print(ir_raw);      // Raw IR value
        Serial.print(",");
        Serial.print(gain_str); // Current gain setting
        Serial.print(",");
        Serial.print(integration_time_str); // Current integration time setting
        Serial.print(",");
        Serial.print(sqm_value, 2); // SQM value in mag/arcsec2 with 2 decimal places
        Serial.println();
      } else {
        // Settings were adjusted, skip this measurement
        last_measurement = current_time;
        return;
      }
    }
    if (mlxSensor.isAvailable()) {
      float vdd, ta, center;
      float corners[4];
      
      if (mlxSensor.readThermalData(vdd, ta, corners, center)) {
        // Output parameters
        Serial.print("$cloud_meta,");
        Serial.print(vdd, 3);
        Serial.print(",");
        Serial.print(ta, 3);
        Serial.println();
        
        // Output corner and center data
        Serial.print("$cloud,");
        Serial.print(corners[0], 2); Serial.print(","); // TL
        Serial.print(corners[1], 2); Serial.print(","); // TR
        Serial.print(corners[2], 2); Serial.print(","); // BL
        Serial.print(corners[3], 2); Serial.print(","); // BR
        Serial.print(center, 2);                         // CTR
        Serial.println();

        // Volitelné: celá teplotní mapa (16x12 = 192 hodnot) v °C
        if (thrmap_streaming) {
          const float *map = mlxSensor.getTemperatureMap();
          if (map != nullptr) {
            Serial.print("$thrmap");
            for (int i = 0; i < MLX90641_PIXEL_COUNT; ++i) {
              Serial.print(i == 0 ? "," : ",");
              Serial.print(map[i], 2);
            }
            Serial.println();
          }
        }
      }
    }

    last_measurement = current_time;
  }

  delay(10); // Small delay to prevent busy waiting
}

