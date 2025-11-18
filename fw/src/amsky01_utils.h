#ifndef AMSKY01_UTILS_H
#define AMSKY01_UTILS_H

#include <Arduino.h>
#include <pico/unique_id.h>

/**
 * Get device serial number from RP2040 unique chip ID
 * Returns 16-character hex string (64-bit ID)
 */
String getDeviceSerialNumber() {
    pico_unique_board_id_t board_id;
    pico_get_unique_board_id(&board_id);
    
    char serial[17];  // 16 hex chars + null terminator
    snprintf(serial, sizeof(serial), 
             "%02X%02X%02X%02X%02X%02X%02X%02X",
             board_id.id[0], board_id.id[1], board_id.id[2], board_id.id[3],
             board_id.id[4], board_id.id[5], board_id.id[6], board_id.id[7]);
    
    return String(serial);
}

#endif // AMSKY01_UTILS_H
