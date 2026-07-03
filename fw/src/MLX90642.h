#ifndef MLX90642_H
#define MLX90642_H

#include <Arduino.h>
#include <Wire.h>

// MLX90642 definitions - 32x24 pixelové IR pole, plně kalibrované (RAM
// obsahuje přímo teploty To ve °C/50, nepotřebuje externí kalibrační
// knihovnu jako starší MLX9064x senzory).
#define MLX90642_I2C_ADDR_DEFAULT 0x66
#define MLX90642_ROWS 24
#define MLX90642_COLS 32
#define MLX90642_PIXEL_COUNT (MLX90642_ROWS * MLX90642_COLS)

class MLX90642 {
private:
    TwoWire* _wire;
    uint8_t i2cAddr;
    bool initialized;
    bool hasValidFrame;

    // Poslední vypočtená teplotní mapa (°C) pro všech 768 pixelů
    float temperatureMap[MLX90642_PIXEL_COUNT];

    bool readWords(uint16_t startAddr, uint16_t *dest, uint16_t numWords);
    void computeRegions(float corners[4], float &center) const;

public:
    MLX90642();

    // Inicializace senzoru (ověří přítomnost na I2C, kalibrace je interní)
    bool begin(TwoWire *wire = &Wire, uint8_t addr = MLX90642_I2C_ADDR_DEFAULT);

    // Dostupnost senzoru (úspěšná inicializace)
    bool isAvailable() const;

    // Načte nový frame (To přímo z RAM), Ta = interní T senzor (°C)
    // vdd není senzorem měřeno, vrací se nominálních 3.3V.
    bool readThermalData(float &vdd, float &ta, float corners[4], float &center);

    // Vrací pointer na poslední platnou teplotní mapu (nebo nullptr pokud není)
    const float *getTemperatureMap() const;
};

#endif
