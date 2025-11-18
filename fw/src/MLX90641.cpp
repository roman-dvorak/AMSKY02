#include "MLX90641.h"

#include "mlx90641-library/headers/MLX90641_API.h"
#include "mlx90641-library/headers/MLX90641_I2C_Driver.h"

MLX90641::MLX90641()
{
    _wire = nullptr;
    initialized = false;
    hasValidFrame = false;
}

bool MLX90641::begin(TwoWire *wire)
{
    _wire = wire;
    initialized = false;
    hasValidFrame = false;

    if (_wire == nullptr)
    {
        Serial.println("# MLX90641: invalid Wire instance");
        return false;
    }

    // Inicializace I2C driveru knihovny (frekvence nastavíme na 400 kHz)
    MLX90641_I2CInit();
    MLX90641_I2CFreqSet(400);

    // Ověření I2C spojení jednoduchým přenosem
    _wire->beginTransmission(MLX90641_I2C_ADDR);
    if (_wire->endTransmission() != 0)
    {
        Serial.println("# MLX90641 thermal sensor initialization failed (I2C)");
        return false;
    }

    // Načtení EEPROM a kalibračních parametrů
    int status = MLX90641_DumpEE(MLX90641_I2C_ADDR, eeData);
    if (status != 0)
    {
        Serial.print("# MLX90641_DumpEE failed, err=");
        Serial.println(status);
        return false;
    }

    status = MLX90641_ExtractParameters(eeData, &calibration);
    if (status != 0)
    {
        Serial.print("# MLX90641_ExtractParameters failed, err=");
        Serial.println(status);
        return false;
    }

    // Nastavíme refresh rate na 4 Hz (011b), aby byl rozumný kompromis mezi šumem a rychlostí
    status = MLX90641_SetRefreshRate(MLX90641_I2C_ADDR, 0b011);
    if (status != 0)
    {
        Serial.print("# MLX90641_SetRefreshRate failed, err=");
        Serial.println(status);
        // Nebereme jako fatální chybu
    }

    initialized = true;
    Serial.println("# MLX90641 thermal sensor initialized successfully");
    return true;
}

bool MLX90641::isAvailable() const
{
    return initialized;
}

bool MLX90641::readThermalData(float &vdd, float &ta, float corners[4], float &center)
{
    if (!initialized)
    {
        return false;
    }

    // Načte kompletní frame (včetně pomocných registrů). Funkce sama čeká na nový frame.
    int status = MLX90641_GetFrameData(MLX90641_I2C_ADDR, frameData);
    if (status < 0)
    {
        Serial.print("# MLX90641_GetFrameData failed, err=");
        Serial.println(status);
        return false;
    }

    vdd = MLX90641_GetVdd(frameData, &calibration);
    ta = MLX90641_GetTa(frameData, &calibration);

    // Emisivita z EEPROM, odražená teplota přibližně Ta-5°C dle datasheetu
    float emissivity = MLX90641_GetEmissivity(&calibration);
    float tr = ta - 5.0f;

    // Spočítá teplotu objektu pro všech 192 pixelů
    MLX90641_CalculateTo(frameData, &calibration, emissivity, tr, temperatureMap);
    hasValidFrame = true;

    // Spočítat rohy a střed z mapy
    computeRegions(corners, center);

    return true;
}

void MLX90641::computeRegions(float corners[4], float &center) const
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

    constexpr int rows = 12;  // MLX90641 má 12 řádků
    constexpr int cols = 16;  // a 16 sloupců

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

    // 4×4 oblasti v rozích
    corners[0] = regionAvg(0, 3, 0, 3);           // TL
    corners[1] = regionAvg(0, 3, cols - 4, cols - 1); // TR
    corners[2] = regionAvg(rows - 4, rows - 1, 0, 3); // BL
    corners[3] = regionAvg(rows - 4, rows - 1, cols - 4, cols - 1); // BR

    // Středová oblast 4×4
    center = regionAvg(4, 7, 6, 9);
}

const float *MLX90641::getTemperatureMap() const
{
    return hasValidFrame ? temperatureMap : nullptr;
}

