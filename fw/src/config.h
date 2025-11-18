#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>
#include <EEPROM.h>

// EEPROM size allocation
#define EEPROM_SIZE 256

// Configuration structure version - increment when changing structure
#define CONFIG_VERSION 1
#define CONFIG_MAGIC 0xA5CA  // Magic number to verify valid config

// Configuration structure stored in EEPROM
struct DeviceConfig {
    uint16_t magic;           // Magic number for validation
    uint8_t version;          // Config structure version
    
    // SQM calibration parameters
    float sqm_offset;         // Offset for SQM calculation (default: 8.5265)
    float sqm_multiplier;     // Multiplier for SQM calculation (default: -2.5)
    float sqm_dark_cap;       // Maximum SQM value for dark sky (default: 23.0)
    
    // Cloud sensor parameters
    float cloud_threshold;    // Temperature difference threshold for cloud detection (°C)
    
    // Alert/trigger output configuration
    bool alert_enabled;       // Enable/disable alert output
    uint8_t alert_pin;        // GPIO pin for alert output (default: TRIGGER_OUT_LED)
    bool alert_on_cloud;      // Trigger alert on cloud detection
    float alert_cloud_temp_threshold;  // Cloud temperature threshold (°C)
    bool alert_on_light;      // Trigger alert on high light (dawn/lights)
    float alert_light_threshold;  // Light threshold in lux for alert
    bool alert_active_high;   // true = alert HIGH when triggered, false = alert LOW
    
    // Measurement intervals (milliseconds)
    uint16_t measurement_interval;  // Default: 2000 ms
    
    // Device identification (optional user-configurable label)
    char device_label[32];    // Custom device label/location
    
    uint16_t checksum;        // Simple checksum for data integrity
};

class ConfigManager {
private:
    DeviceConfig config;
    
    // Calculate simple checksum
    uint16_t calculateChecksum() {
        uint16_t sum = 0;
        uint8_t* data = (uint8_t*)&config;
        // Checksum everything except the checksum field itself
        for (size_t i = 0; i < sizeof(DeviceConfig) - sizeof(uint16_t); i++) {
            sum += data[i];
        }
        return sum;
    }
    
    // Load default configuration
    void loadDefaults() {
        config.magic = CONFIG_MAGIC;
        config.version = CONFIG_VERSION;
        
        // SQM defaults
        config.sqm_offset = 8.5265;
        config.sqm_multiplier = -2.5;
        config.sqm_dark_cap = 23.0;
        
        // Cloud sensor defaults
        config.cloud_threshold = 5.0;  // 5°C difference
        
        // Alert defaults
        config.alert_enabled = false;
        config.alert_pin = 27;  // TRIGGER_OUT_LED pin
        config.alert_on_cloud = true;
        config.alert_cloud_temp_threshold = -10.0;  // Alert if sky temp < -10°C (clouds)
        config.alert_on_light = true;
        config.alert_light_threshold = 10.0;  // Alert if light > 10 lux (dawn/lights)
        config.alert_active_high = true;  // HIGH = alert active
        
        // Timing defaults
        config.measurement_interval = 2000;
        
        // Device label
        strncpy(config.device_label, "AMSKY01", sizeof(config.device_label));
        
        config.checksum = calculateChecksum();
    }
    
public:
    ConfigManager() {
        EEPROM.begin(EEPROM_SIZE);
    }
    
    // Initialize configuration - load from EEPROM or use defaults
    bool begin() {
        EEPROM.get(0, config);
        
        // Verify magic number and checksum
        if (config.magic != CONFIG_MAGIC || 
            config.version != CONFIG_VERSION ||
            config.checksum != calculateChecksum()) {
            Serial.println("# Config invalid or not found, loading defaults");
            loadDefaults();
            save();  // Save defaults to EEPROM
            return false;
        }
        
        Serial.println("# Config loaded from EEPROM");
        return true;
    }
    
    // Save configuration to EEPROM
    bool save() {
        config.checksum = calculateChecksum();
        EEPROM.put(0, config);
        bool success = EEPROM.commit();
        if (success) {
            Serial.println("# Config saved to EEPROM");
        } else {
            Serial.println("# Config save failed");
        }
        return success;
    }
    
    // Reset to defaults
    void reset() {
        Serial.println("# Resetting config to defaults");
        loadDefaults();
        save();
    }
    
    // Getters
    float getSqmOffset() { return config.sqm_offset; }
    float getSqmMultiplier() { return config.sqm_multiplier; }
    float getSqmDarkCap() { return config.sqm_dark_cap; }
    float getCloudThreshold() { return config.cloud_threshold; }
    bool isAlertEnabled() { return config.alert_enabled; }
    uint8_t getAlertPin() { return config.alert_pin; }
    bool isAlertOnCloud() { return config.alert_on_cloud; }
    float getAlertCloudTempThreshold() { return config.alert_cloud_temp_threshold; }
    bool isAlertOnLight() { return config.alert_on_light; }
    float getAlertLightThreshold() { return config.alert_light_threshold; }
    bool isAlertActiveHigh() { return config.alert_active_high; }
    uint16_t getMeasurementInterval() { return config.measurement_interval; }
    const char* getDeviceLabel() { return config.device_label; }
    
    // Setters
    void setSqmOffset(float value) { config.sqm_offset = value; }
    void setSqmMultiplier(float value) { config.sqm_multiplier = value; }
    void setSqmDarkCap(float value) { config.sqm_dark_cap = value; }
    void setCloudThreshold(float value) { config.cloud_threshold = value; }
    void setAlertEnabled(bool value) { config.alert_enabled = value; }
    void setAlertPin(uint8_t value) { config.alert_pin = value; }
    void setAlertOnCloud(bool value) { config.alert_on_cloud = value; }
    void setAlertCloudTempThreshold(float value) { config.alert_cloud_temp_threshold = value; }
    void setAlertOnLight(bool value) { config.alert_on_light = value; }
    void setAlertLightThreshold(float value) { config.alert_light_threshold = value; }
    void setAlertActiveHigh(bool value) { config.alert_active_high = value; }
    void setMeasurementInterval(uint16_t value) { config.measurement_interval = value; }
    void setDeviceLabel(const char* label) { 
        strncpy(config.device_label, label, sizeof(config.device_label) - 1);
        config.device_label[sizeof(config.device_label) - 1] = '\0';
    }
    
    // Print current configuration
    void printConfig() {
        Serial.println("# === Current Configuration ===");
        Serial.print("# SQM Offset: "); Serial.println(config.sqm_offset, 4);
        Serial.print("# SQM Multiplier: "); Serial.println(config.sqm_multiplier, 4);
        Serial.print("# SQM Dark Cap: "); Serial.println(config.sqm_dark_cap, 2);
        Serial.print("# Cloud Threshold: "); Serial.println(config.cloud_threshold, 2);
        Serial.print("# Alert Enabled: "); Serial.println(config.alert_enabled ? "YES" : "NO");
        Serial.print("# Alert Pin: GPIO"); Serial.println(config.alert_pin);
        Serial.print("# Alert on Cloud: "); Serial.println(config.alert_on_cloud ? "YES" : "NO");
        Serial.print("# Alert Cloud Temp Threshold: "); Serial.print(config.alert_cloud_temp_threshold, 2); Serial.println(" °C");
        Serial.print("# Alert on Light: "); Serial.println(config.alert_on_light ? "YES" : "NO");
        Serial.print("# Alert Light Threshold: "); Serial.print(config.alert_light_threshold, 2); Serial.println(" lux");
        Serial.print("# Alert Active High: "); Serial.println(config.alert_active_high ? "YES" : "NO");
        Serial.print("# Measurement Interval: "); Serial.print(config.measurement_interval); Serial.println(" ms");
        Serial.print("# Device Label: "); Serial.println(config.device_label);
        Serial.println("# ============================");
    }
};

#endif // CONFIG_H
