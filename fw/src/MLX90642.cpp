#include "MLX90642.h"

// RAM adresy (viz datasheet MLX90642, kap. 3.1.5.3)
#define MLX90642_RAM_TO_START   0x342C  // 768 slov, To[i:j] = RAM/50 [°C]
#define MLX90642_RAM_T_SENSOR   0x3A2C  // 1 slovo, Tsensor = RAM/100 [°C]

// Max. počet slov čtených v jedné I2C transakci (drží se pod velikostí
// Wire bufferu na RP2040 - 256 B). 64 slov = 128 B dat + 2 B adresy.
static const uint16_t MLX90642_READ_CHUNK_WORDS = 64;

MLX90642::MLX90642()
{
    _wire = nullptr;
    i2cAddr = MLX90642_I2C_ADDR_DEFAULT;
    initialized = false;
    hasValidFrame = false;
}

bool MLX90642::readWords(uint16_t startAddr, uint16_t *dest, uint16_t numWords)
{
    uint16_t remaining = numWords;
    uint16_t addr = startAddr;
    uint16_t offset = 0;

    while (remaining > 0)
    {
        uint16_t chunk = (remaining > MLX90642_READ_CHUNK_WORDS) ? MLX90642_READ_CHUNK_WORDS : remaining;

        _wire->beginTransmission(i2cAddr);
        _wire->write((uint8_t)(addr >> 8));
        _wire->write((uint8_t)(addr & 0xFF));
        if (_wire->endTransmission(false) != 0) // repeated START, bez STOP
        {
            return false;
        }

        uint16_t bytesRequested = chunk * 2;
        uint16_t received = _wire->requestFrom((int)i2cAddr, (int)bytesRequested, (int)true);
        if (received != bytesRequested)
        {
            return false;
        }

        for (uint16_t i = 0; i < chunk; ++i)
        {
            uint8_t msb = _wire->read();
            uint8_t lsb = _wire->read();
            dest[offset + i] = ((uint16_t)msb << 8) | lsb;
        }

        offset += chunk;
        addr += chunk * 2; // adresy jsou po slovech (2 B krok)
        remaining -= chunk;
    }

    return true;
}

bool MLX90642::begin(TwoWire *wire, uint8_t addr)
{
    _wire = wire;
    i2cAddr = addr;
    initialized = false;
    hasValidFrame = false;

    if (_wire == nullptr)
    {
        Serial.print("# MLX90642 (0x");
        Serial.print(i2cAddr, HEX);
        Serial.println("): invalid Wire instance");
        return false;
    }

    // Ověření I2C spojení jednoduchým přenosem
    _wire->beginTransmission(i2cAddr);
    if (_wire->endTransmission() != 0)
    {
        Serial.print("# MLX90642 (0x");
        Serial.print(i2cAddr, HEX);
        Serial.println(") thermal sensor initialization failed (I2C)");
        return false;
    }

    // Senzor je tovární kalibrovaný a po POR běží v continuous módu
    // s výchozím refresh rate 8 Hz - není potřeba žádná další inicializace.
    initialized = true;
    Serial.print("# MLX90642 (0x");
    Serial.print(i2cAddr, HEX);
    Serial.println(") thermal sensor initialized successfully");
    return true;
}

bool MLX90642::isAvailable() const
{
    return initialized;
}

bool MLX90642::readThermalData(float &vdd, float &ta, float corners[4], float &center)
{
    if (!initialized)
    {
        return false;
    }

    uint16_t rawTo[MLX90642_PIXEL_COUNT];
    if (!readWords(MLX90642_RAM_TO_START, rawTo, MLX90642_PIXEL_COUNT))
    {
        Serial.print("# MLX90642 (0x");
        Serial.print(i2cAddr, HEX);
        Serial.println(") readWords(To) failed");
        return false;
    }

    for (int i = 0; i < MLX90642_PIXEL_COUNT; ++i)
    {
        temperatureMap[i] = (float)(int16_t)rawTo[i] / 50.0f;
    }

    uint16_t rawTsensor;
    if (!readWords(MLX90642_RAM_T_SENSOR, &rawTsensor, 1))
    {
        Serial.print("# MLX90642 (0x");
        Serial.print(i2cAddr, HEX);
        Serial.println(") readWords(Tsensor) failed");
        return false;
    }
    ta = (float)(int16_t)rawTsensor / 100.0f;

    // MLX90642 nemá zvlášť dostupné VDD - vracíme nominální hodnotu
    vdd = 3.3f;

    hasValidFrame = true;
    computeRegions(corners, center);

    return true;
}

void MLX90642::computeRegions(float corners[4], float &center) const
{
    if (!hasValidFrame)
    {
        for (int i = 0; i < 4; ++i)
        {
            corners[i] = NAN;
        }
        center = NAN;
        return;
    }

    constexpr int rows = MLX90642_ROWS;
    constexpr int cols = MLX90642_COLS;

    auto regionAvg = [&](int r0, int r1, int c0, int c1) {
        float sum = 0.0f;
        int count = 0;
        for (int r = r0; r <= r1; ++r)
        {
            for (int c = c0; c <= c1; ++c)
            {
                int idx = r * cols + c;
                sum += temperatureMap[idx];
                ++count;
            }
        }
        return (count > 0) ? (sum / count) : NAN;
    };

    // 4x4 oblasti v rozích
    corners[0] = regionAvg(0, 3, 0, 3);               // TL
    corners[1] = regionAvg(0, 3, cols - 4, cols - 1);  // TR
    corners[2] = regionAvg(rows - 4, rows - 1, 0, 3);  // BL
    corners[3] = regionAvg(rows - 4, rows - 1, cols - 4, cols - 1); // BR

    // Středová oblast 4x4
    center = regionAvg(rows / 2 - 2, rows / 2 + 1, cols / 2 - 2, cols / 2 + 1);
}

const float *MLX90642::getTemperatureMap() const
{
    return hasValidFrame ? temperatureMap : nullptr;
}
