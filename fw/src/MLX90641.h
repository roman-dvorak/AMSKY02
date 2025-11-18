#ifndef MLX90641_H
#define MLX90641_H

#include <Arduino.h>
#include <Wire.h>

#include "mlx90641-library/headers/MLX90641_API.h"

// MLX90641 definitions
#define MLX90641_I2C_ADDR 0x33
#define MLX90641_PIXEL_COUNT 192

class MLX90641 {
private:
    TwoWire* _wire;
    bool initialized;
    bool hasValidFrame;

    // Kalibrační data a frame buffer z oficiální knihovny
    uint16_t eeData[832];
    uint16_t frameData[242];
    paramsMLX90641 calibration;

    // Poslední vypočtená teplotní mapa (°C) pro všech 192 pixelů
    float temperatureMap[MLX90641_PIXEL_COUNT];

    void computeRegions(float corners[4], float &center) const;

public:
    MLX90641();

    // Inicializace senzoru a načtení kalibračních dat
    bool begin(TwoWire *wire = &Wire);

    // Dostupnost senzoru (úspěšná inicializace)
    bool isAvailable() const;

    // Načte nový frame, spočítá Vdd, Ta, celou mapu To[] a rohové/středové průměry
    bool readThermalData(float &vdd, float &ta, float corners[4], float &center);

    // Vrací pointer na poslední platnou teplotní mapu (nebo nullptr pokud není)
    const float *getTemperatureMap() const;
};

#endif
