#ifndef PCA9543_H
#define PCA9543_H

#include <Arduino.h>
#include <Wire.h>

// Driver pro I2C mux/switch PCA9543A (2-kanálový, s interrupt flagy)
// Datasheet: control register - bit0/bit1 = enable kanál 0/1 (lze i oba
// najednou), horní 2 bity (INT0/INT1, read-only) reportují stav interrupt
// pinů podřízených zařízení.
class PCA9543 {
public:
    static const uint8_t DEFAULT_ADDRESS = 0x70; // A0=A1=GND

    bool begin(TwoWire *wire, uint8_t address = DEFAULT_ADDRESS) {
        _wire = wire;
        _address = address;
        _current_mask = 0xFF; // vynutí zápis při první selectChannel/disableAll

        // Ověř přítomnost muxu na sběrnici
        _wire->beginTransmission(_address);
        bool ok = (_wire->endTransmission() == 0);
        if (ok) {
            disableAll();
        }
        return ok;
    }

    // Vybere právě jeden kanál (0 nebo 1), ostatní odpojí
    bool selectChannel(uint8_t channel) {
        if (channel > 1) return false;
        return writeMask(1 << channel);
    }

    // Odpojí oba kanály (bus izolovaný, jen mux zůstává adresovatelný)
    bool disableAll() {
        return writeMask(0x00);
    }

    uint8_t currentChannelMask() const { return _current_mask & 0x03; }

private:
    TwoWire *_wire = nullptr;
    uint8_t _address = DEFAULT_ADDRESS;
    uint8_t _current_mask = 0xFF;

    bool writeMask(uint8_t mask) {
        if (_wire == nullptr) return false;
        if (_current_mask == mask) return true; // nic se nemění, ušetři I2C transakci

        _wire->beginTransmission(_address);
        _wire->write(mask & 0x03);
        bool ok = (_wire->endTransmission() == 0);
        if (ok) {
            _current_mask = mask;
        }
        return ok;
    }
};

#endif // PCA9543_H
