#include "AMS_TSL2591.h"

AMS_TSL2591::AMS_TSL2591() : tsl(2591) {
    current_gain = TSL2591_GAIN_MED;
    current_integration_time = TSL2591_INTEGRATIONTIME_300MS;
    last_gain_adjustment = 0;
    previous_measurement = 0;
    improvement_detected = false;
    last_adjustment_type = ADJUST_NONE;
}

bool AMS_TSL2591::begin(TwoWire *wire) {
    if (tsl.begin(wire)) {
        // Configure TSL2591 sensor
        current_gain = TSL2591_GAIN_MED;
        tsl.setGain(current_gain);
        tsl.setTiming(TSL2591_INTEGRATIONTIME_300MS);
        
        Serial.println("# TSL2591 light sensor initialized successfully");
        Serial.print("# Initial gain: ");
        Serial.println(getGainString(current_gain));
        
        return true;
    }
    
    Serial.println("# TSL2591 light sensor initialization failed");
    return false;
}

bool AMS_TSL2591::isAvailable() const {
    return true; // If initialization was successful, sensor is available
}

const char* AMS_TSL2591::getGainString(tsl2591Gain_t gain) {
    switch(gain) {
        case TSL2591_GAIN_LOW:  return "1";
        case TSL2591_GAIN_MED:  return "25";
        case TSL2591_GAIN_HIGH: return "428";
        case TSL2591_GAIN_MAX:  return "9876";
        default: return "unknown";
    }
}

float AMS_TSL2591::getGainValue(tsl2591Gain_t gain) {
    switch(gain) {
        case TSL2591_GAIN_LOW:  return 1.0;
        case TSL2591_GAIN_MED:  return 25.0;
        case TSL2591_GAIN_HIGH: return 428.0;
        case TSL2591_GAIN_MAX:  return 9876.0;
        default: return 1.0;
    }
}

float AMS_TSL2591::getIntegrationTimeMs(tsl2591IntegrationTime_t integrationTime) {
    switch(integrationTime) {
        case TSL2591_INTEGRATIONTIME_100MS: return 100.0;
        case TSL2591_INTEGRATIONTIME_200MS: return 200.0;
        case TSL2591_INTEGRATIONTIME_300MS: return 300.0;
        case TSL2591_INTEGRATIONTIME_400MS: return 400.0;
        case TSL2591_INTEGRATIONTIME_500MS: return 500.0;
        case TSL2591_INTEGRATIONTIME_600MS: return 600.0;
        default: return 300.0;
    }
}

const char* AMS_TSL2591::getIntegrationTimeString(tsl2591IntegrationTime_t integrationTime) {
    switch(integrationTime) {
        case TSL2591_INTEGRATIONTIME_100MS: return "100";
        case TSL2591_INTEGRATIONTIME_200MS: return "200";
        case TSL2591_INTEGRATIONTIME_300MS: return "300";
        case TSL2591_INTEGRATIONTIME_400MS: return "400";
        case TSL2591_INTEGRATIONTIME_500MS: return "500";
        case TSL2591_INTEGRATIONTIME_600MS: return "600";
        default: return "300";
    }
}

bool AMS_TSL2591::adjustGainAndIntegrationTime(uint16_t full_value) {
    tsl2591Gain_t new_gain = current_gain;
    tsl2591IntegrationTime_t new_integration_time = current_integration_time;
    bool changed = false;
    
    // Intelligent adaptive adjustment
    improvement_detected = (full_value != previous_measurement);

    if (!improvement_detected) {
        // Alternate adjustment to determine efficiency
        last_adjustment_type = (last_adjustment_type == ADJUST_GAIN) ? ADJUST_INTEGRATION : ADJUST_GAIN;
    } else {
        last_adjustment_type = ADJUST_BOTH;
    }

    previous_measurement = full_value;
    
    if (last_adjustment_type == ADJUST_GAIN || last_adjustment_type == ADJUST_BOTH) {
        // Handle extreme saturation with priority on gain reduction
        if (full_value > EXTREME_SATURATED_THRESHOLD) {
            // Emergency: extreme saturation - reduce gain aggressively first
            if (current_gain != TSL2591_GAIN_LOW) {
                // Drop gain more aggressively for extreme saturation
                switch(current_gain) {
                    case TSL2591_GAIN_MAX:  new_gain = TSL2591_GAIN_MED; break;  // Skip HIGH gain
                    case TSL2591_GAIN_HIGH: new_gain = TSL2591_GAIN_LOW; break;  // Skip MED gain
                    case TSL2591_GAIN_MED:  new_gain = TSL2591_GAIN_LOW; break;
                    default: break;
                }
                changed = true;
            }
        }
    }

    if (last_adjustment_type == ADJUST_INTEGRATION || last_adjustment_type == ADJUST_BOTH) {
        // Also reduce integration time aggressively
        if (full_value > EXTREME_SATURATED_THRESHOLD) {
            if (current_integration_time != TSL2591_INTEGRATIONTIME_100MS) {
                switch(current_integration_time) {
                    case TSL2591_INTEGRATIONTIME_600MS: new_integration_time = TSL2591_INTEGRATIONTIME_300MS; break; // Skip 500MS and 400MS
                    case TSL2591_INTEGRATIONTIME_500MS: new_integration_time = TSL2591_INTEGRATIONTIME_200MS; break; // Skip 400MS and 300MS
                    case TSL2591_INTEGRATIONTIME_400MS: new_integration_time = TSL2591_INTEGRATIONTIME_100MS; break; // Skip 300MS and 200MS
                    case TSL2591_INTEGRATIONTIME_300MS: new_integration_time = TSL2591_INTEGRATIONTIME_100MS; break; // Skip 200MS
                    case TSL2591_INTEGRATIONTIME_200MS: new_integration_time = TSL2591_INTEGRATIONTIME_100MS; break;
                    default: break;
                }
                changed = true;
            }
        }
    }
    
    // Handle regular saturation with smart alternating 
    if (full_value > GAIN_SATURATED_THRESHOLD && full_value <= EXTREME_SATURATED_THRESHOLD) {
        if (last_adjustment_type == ADJUST_GAIN || last_adjustment_type == ADJUST_BOTH) {
            // Priority: reduce gain and integration time together to prevent saturation
            // First, try to reduce gain if not at minimum
            if (current_gain != TSL2591_GAIN_LOW) {
                switch(current_gain) {
                    case TSL2591_GAIN_MAX:  new_gain = TSL2591_GAIN_HIGH; break;
                    case TSL2591_GAIN_HIGH: new_gain = TSL2591_GAIN_MED; break;
                    case TSL2591_GAIN_MED:  new_gain = TSL2591_GAIN_LOW; break;
                    default: break;
                }
                changed = true;
            }
            // Also try to reduce integration time if not at minimum (parallel reduction)
            if (current_integration_time != TSL2591_INTEGRATIONTIME_100MS) {
                switch(current_integration_time) {
                    case TSL2591_INTEGRATIONTIME_600MS: new_integration_time = TSL2591_INTEGRATIONTIME_500MS; break;
                    case TSL2591_INTEGRATIONTIME_500MS: new_integration_time = TSL2591_INTEGRATIONTIME_400MS; break;
                    case TSL2591_INTEGRATIONTIME_400MS: new_integration_time = TSL2591_INTEGRATIONTIME_300MS; break;
                    case TSL2591_INTEGRATIONTIME_300MS: new_integration_time = TSL2591_INTEGRATIONTIME_200MS; break;
                    case TSL2591_INTEGRATIONTIME_200MS: new_integration_time = TSL2591_INTEGRATIONTIME_100MS; break;
                    default: break;
                }
                changed = true;
            }
        }
    }
    // If signal is very low, try to increase integration time first, then gain
    else if (full_value < INTEGRATION_TIME_INCREASE_THRESHOLD) {
        if (current_integration_time != TSL2591_INTEGRATIONTIME_600MS) {
            switch(current_integration_time) {
                case TSL2591_INTEGRATIONTIME_100MS: new_integration_time = TSL2591_INTEGRATIONTIME_200MS; break;
                case TSL2591_INTEGRATIONTIME_200MS: new_integration_time = TSL2591_INTEGRATIONTIME_300MS; break;
                case TSL2591_INTEGRATIONTIME_300MS: new_integration_time = TSL2591_INTEGRATIONTIME_400MS; break;
                case TSL2591_INTEGRATIONTIME_400MS: new_integration_time = TSL2591_INTEGRATIONTIME_500MS; break;
                case TSL2591_INTEGRATIONTIME_500MS: new_integration_time = TSL2591_INTEGRATIONTIME_600MS; break;
                default: break;
            }
            changed = true;
        } else if (current_gain != TSL2591_GAIN_MAX) {
            switch(current_gain) {
                case TSL2591_GAIN_LOW:  new_gain = TSL2591_GAIN_MED; break;
                case TSL2591_GAIN_MED:  new_gain = TSL2591_GAIN_HIGH; break;
                case TSL2591_GAIN_HIGH: new_gain = TSL2591_GAIN_MAX; break;
                default: break;
            }
            changed = true;
        }
    }
    // If signal is a bit high, but not saturated, decrease integration time if possible
    else if (full_value > INTEGRATION_TIME_DECREASE_THRESHOLD) {
        if (current_integration_time != TSL2591_INTEGRATIONTIME_100MS) {
            switch(current_integration_time) {
                case TSL2591_INTEGRATIONTIME_600MS: new_integration_time = TSL2591_INTEGRATIONTIME_500MS; break;
                case TSL2591_INTEGRATIONTIME_500MS: new_integration_time = TSL2591_INTEGRATIONTIME_400MS; break;
                case TSL2591_INTEGRATIONTIME_400MS: new_integration_time = TSL2591_INTEGRATIONTIME_300MS; break;
                case TSL2591_INTEGRATIONTIME_300MS: new_integration_time = TSL2591_INTEGRATIONTIME_200MS; break;
                case TSL2591_INTEGRATIONTIME_200MS: new_integration_time = TSL2591_INTEGRATIONTIME_100MS; break;
                default: break;
            }
            changed = true;
        }
    }
    // If signal is a bit low, but not very low, increase integration time if possible
    else if (full_value < GAIN_TOO_LOW_THRESHOLD) {
        if (current_integration_time != TSL2591_INTEGRATIONTIME_600MS) {
            switch(current_integration_time) {
                case TSL2591_INTEGRATIONTIME_100MS: new_integration_time = TSL2591_INTEGRATIONTIME_200MS; break;
                case TSL2591_INTEGRATIONTIME_200MS: new_integration_time = TSL2591_INTEGRATIONTIME_300MS; break;
                case TSL2591_INTEGRATIONTIME_300MS: new_integration_time = TSL2591_INTEGRATIONTIME_400MS; break;
                case TSL2591_INTEGRATIONTIME_400MS: new_integration_time = TSL2591_INTEGRATIONTIME_500MS; break;
                case TSL2591_INTEGRATIONTIME_500MS: new_integration_time = TSL2591_INTEGRATIONTIME_600MS; break;
                default: break;
            }
            changed = true;
        }
    }

    if (!changed || (new_gain == current_gain && new_integration_time == current_integration_time)) {
        return false;
    }

    // Apply new gain and integration time
    current_gain = new_gain;
    current_integration_time = new_integration_time;
    
    tsl.setGain(current_gain);
    tsl.setTiming(current_integration_time);

    Serial.print("# Gain adjusted to: ");
    Serial.println(getGainString(current_gain));

    Serial.print("# Integration time adjusted to: ");
    Serial.println((int)current_integration_time * 100);

    return true;
}

bool AMS_TSL2591::readLightData(float &normalized_lux, uint16_t &full_raw, uint16_t &ir_raw, 
                                 const char* &gain_str, const char* &integration_time_str) {
    uint32_t lum = tsl.getFullLuminosity();

    ir_raw = lum >> 16;
    full_raw = lum & 0xFFFF;
    
    // Calculate actual lux value
    float lux = tsl.calculateLux(full_raw, ir_raw);
    
    // Normalize the lux value by gain and integration time
    float normalization_factor = getGainValue(current_gain) * getIntegrationTimeMs(current_integration_time) / 300.0; // 300ms is the base integration time
    normalized_lux = lux / normalization_factor;
    
    // Check if we need to adjust gain and integration time (but not too frequently)
    unsigned long current_time = millis();
    if (current_time - last_gain_adjustment >= GAIN_ADJUSTMENT_INTERVAL) {
        if (adjustGainAndIntegrationTime(full_raw)) {
            last_gain_adjustment = current_time;
            // Return false to indicate that settings changed and measurement should be skipped
            return false;
        }
    }

    gain_str = getGainString(current_gain);
    integration_time_str = getIntegrationTimeString(current_integration_time);
    
    return true;
}
