#include <Arduino.h>
#include <Wire.h>

#include "mlx90641-library/headers/MLX90641_I2C_Driver.h"

// Používáme I2C sběrnici Wire1, která je v main.cpp nakonfigurovaná
extern TwoWire Wire1;

static TwoWire &mlxWire = Wire1;

void MLX90641_I2CInit(void)
{
    // Inicializace a piny se řeší v uživatelském kódu (main.cpp)
}

void MLX90641_I2CFreqSet(int freq)
{
    // freq je v kHz
    mlxWire.setClock((uint32_t)freq * 1000U);
}

int MLX90641_I2CGeneralReset(void)
{
    // General Call reset (adresa 0x00, data 0x06)
    mlxWire.beginTransmission(0x00);
    mlxWire.write(0x06);
    uint8_t res = mlxWire.endTransmission();
    delay(5);
    return (res == 0) ? 0 : -1;
}

int MLX90641_I2CRead(uint8_t slaveAddr, uint16_t startAddress,
                     uint16_t nMemAddressRead, uint16_t *data)
{
    const uint8_t addr = slaveAddr; // Arduino používá 7bit adresu
    const uint16_t MAX_WORDS_PER_CHUNK = 16; // 16 slov = 32 bajtů (I2C buffer)

    uint16_t wordsRead = 0;

    while (wordsRead < nMemAddressRead)
    {
        uint16_t chunkWords = nMemAddressRead - wordsRead;
        if (chunkWords > MAX_WORDS_PER_CHUNK)
            chunkWords = MAX_WORDS_PER_CHUNK;

        uint16_t currentAddress = startAddress + wordsRead;

        mlxWire.beginTransmission(addr);
        mlxWire.write(currentAddress >> 8);
        mlxWire.write(currentAddress & 0xFF);
        if (mlxWire.endTransmission(false) != 0)
        {
            return -1;
        }

        uint8_t toRead = (uint8_t)(chunkWords * 2);
        uint8_t received = mlxWire.requestFrom(addr, toRead);
        if (received != toRead)
        {
            return -1;
        }

        for (uint16_t i = 0; i < chunkWords; ++i)
        {
            int hi = mlxWire.read();
            int lo = mlxWire.read();
            if (hi < 0 || lo < 0)
            {
                return -1;
            }
            data[wordsRead + i] = (uint16_t)((hi << 8) | lo);
        }

        wordsRead += chunkWords;
        delay(2); // krátká pauza mezi bloky
    }

    return 0;
}

int MLX90641_I2CWrite(uint8_t slaveAddr, uint16_t writeAddress, uint16_t data)
{
    const uint8_t addr = slaveAddr;

    mlxWire.beginTransmission(addr);
    mlxWire.write(writeAddress >> 8);
    mlxWire.write(writeAddress & 0xFF);
    mlxWire.write(data >> 8);
    mlxWire.write(data & 0xFF);
    uint8_t res = mlxWire.endTransmission();

    if (res != 0)
    {
        return -1;
    }

    // Volitelné ověření zápisu – knihovna to používá v referenční implementaci
    uint16_t check = 0;
    if (MLX90641_I2CRead(slaveAddr, writeAddress, 1, &check) != 0)
    {
        return -2;
    }
    if (check != data)
    {
        return -3;
    }

    return 0;
}
