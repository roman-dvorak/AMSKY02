#ifndef AMS_TSL2591_H
#define AMS_TSL2591_H

#include <Arduino.h>
#include <Adafruit_TSL2591.h>

class AMS_TSL2591 {
private:
    Adafruit_TSL2591 tsl;
    
    // Auto-gain variables
    tsl2591Gain_t current_gain;
    tsl2591IntegrationTime_t current_integration_time;
    unsigned long last_gain_adjustment;
    uint16_t previous_measurement;
    bool improvement_detected;
    
    // Moving average buffers
    static const uint8_t MOVING_AVG_SIZE = 16;
    uint16_t full_buffer[MOVING_AVG_SIZE];
    uint16_t ir_buffer[MOVING_AVG_SIZE];
    uint8_t buffer_index;
    uint8_t buffer_count;
    
    // Thresholds
    static const unsigned long GAIN_ADJUSTMENT_INTERVAL = 5000;
    static const uint16_t GAIN_SATURATED_THRESHOLD = 32000;
    static const uint16_t EXTREME_SATURATED_THRESHOLD = 35000;
    // Target window for raw full spectrum counts
    static const uint16_t GAIN_TOO_LOW_THRESHOLD = 10000;   // below -> increase
    static const uint16_t INTEGRATION_TIME_INCREASE_THRESHOLD = 1500;
    static const uint16_t INTEGRATION_TIME_DECREASE_THRESHOLD = 30000; // above -> decrease
    
    // Smart alternating adjustment tracking
    enum LastAdjustmentType {
        ADJUST_NONE = 0,
        ADJUST_GAIN = 1,
        ADJUST_INTEGRATION = 2,
        ADJUST_BOTH = 3
    };
    LastAdjustmentType last_adjustment_type;
    
    // Helper functions
    const char* getGainString(tsl2591Gain_t gain);
    float getGainValue(tsl2591Gain_t gain);
    float getIntegrationTimeMs(tsl2591IntegrationTime_t integrationTime);
    const char* getIntegrationTimeString(tsl2591IntegrationTime_t integrationTime);
    bool adjustGainAndIntegrationTime(uint16_t full_value);
    float calculateLuxFromRaw(uint16_t ch0_full, uint16_t ch1_ir);
    
public:
    // Constructor
    AMS_TSL2591();
    
    // Initialization
    bool begin(TwoWire *wire = &Wire);
    
    // Status
    bool isAvailable() const;
    
    // Measurement
    bool readLightData(uint32_t &ulux, uint16_t &full_avg, uint16_t &ir_avg, 
                       const char* &gain_str, const char* &integration_time_str);
    
    // Settings
    tsl2591Gain_t getCurrentGain() const { return current_gain; }
    tsl2591IntegrationTime_t getCurrentIntegrationTime() const { return current_integration_time; }
};

#endif
