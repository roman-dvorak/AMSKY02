#ifndef SQM_UTILS_H
#define SQM_UTILS_H

#include <math.h>

/**
 * TSL2591 SQM calculation algorithm
 * 
 * Algoritmus podle specifikace:
 * 1) Změř raw hodnoty kanálů (ir_raw = CH1, full_raw = CH0)
 * 2) Volitelná teplotní korekce (zakomentováno)
 * 3) Viditelná složka (vis_raw = full_raw - ir_raw)
 * 4) Normalizace na referenci 200ms a na gain
 * 5) Převod na mag/arcsec^2 pomocí ln()
 * 6) Odhad chyby
 */

// SQM constants - converted to configurable parameters
// These values should come from config, here are defaults for reference:
// SQM_OFFSET_BASE = 12.6 (základní konstanta pro výpočet)
// SQM_MAGNITUDE_CONSTANT = 1.086 (konstanta pro ln() konverzi a chybu)

struct SQMResult {
    float mpsas;     // Jas oblohy v mag/arcsec^2
    float dmpsas;    // Odhad chyby
    bool valid;      // Je měření validní?
};

/**
 * Vypočítá SQM z raw hodnot senzoru TSL2591
 * 
 * @param ir_raw        Raw IR hodnota (CH1)
 * @param full_raw      Raw FULL hodnota (CH0 = VIS + IR)
 * @param gainValue     Aktuální zesílení senzoru
 * @param integrationMs Integrační čas v milisekundách
 * @param niter         Počet iterací měření pro součítání
 * @param sqmOffsetBase Základní konstanta pro výpočet (typicky 12.6)
 * @param sqmMagnitude  Konstanta pro konverzi ln() (typicky 1.086)
 * @param calibrationOffset Kalibrační offset (může být 0.0)
 * 
 * @return SQMResult struktura s výsledkem a validací
 */
inline SQMResult calculate_sqm_from_raw(
    uint16_t ir_raw,
    uint16_t full_raw,
    float gainValue,
    float integrationMs,
    uint8_t niter,
    float sqmOffsetBase,
    float sqmMagnitude,
    float calibrationOffset
) {
    SQMResult result = {0.0f, 0.0f, false};
    
    // 1) Raw hodnoty jsou již naměřeny (parametry)
    // ir_raw   = CH1 (IR)
    // full_raw = CH0 (FULL = VIS + IR)
    
    // 2) Teplotní korekce - ZAKOMENTOVÁNA
    // if (temperatureOptional is available) {
    //     ir_raw   = ir_raw   * (temperature * irSlope   + irIntercept)
    //     full_raw = full_raw * (temperature * fullSlope + fullIntercept)
    // }
    
    // 3) Viditelná složka
    float vis_raw = (float)full_raw - (float)ir_raw;
    if (vis_raw <= 0.0f) {
        // Invalidní měření - nižší viditelná složka
        result.valid = false;
        return result;
    }
    
    // 4) Normalizace na referenci 200 ms a na gain
    // normalization = gainValue * (integrationMs / 200.0) * niter
    float normalization = gainValue * (integrationMs / 200.0f) * (float)niter;
    float VIS = vis_raw / normalization;
    
    if (VIS <= 0.0f) {
        // Invalidní měření - normalizovaná viditelná složka je nula nebo negativní
        result.valid = false;
        return result;
    }
    
    // 5) Převod na mag/arcsec^2
    // mpsas = sqmOffsetBase - sqmMagnitude * ln(VIS) + calibrationOffset
    // (ln je přirozený logaritmus)
    result.mpsas = sqmOffsetBase - sqmMagnitude * logf(VIS) + calibrationOffset;
    
    // 6) Odhad chyby (podle knihovny; bere sqrt z nenormalizovaného vis_raw)
    // dmpsas = sqmMagnitude / sqrt(vis_raw)
    result.dmpsas = sqmMagnitude / sqrtf(vis_raw);
    
    result.valid = true;
    return result;
}

/**
 * Zjednodušená verze pro výpočet SQM z již vypočítané normalizované viditelné složky
 * (pro compatibility se starším kódem)
 * 
 * @param vis_normalized Normalizovaná viditelná složka (VIS)
 * @param sqmOffsetBase Základní konstanta pro výpočet (typicky 12.6)
 * @param sqmMagnitude Konstanta pro konverzi ln() (typicky 1.086)
 * @param calibrationOffset Kalibrační offset
 * 
 * @return SQMResult struktura s výsledkem
 */
inline SQMResult calculate_sqm_from_normalized_vis(
    float vis_normalized,
    float sqmOffsetBase,
    float sqmMagnitude,
    float calibrationOffset
) {
    SQMResult result = {0.0f, 0.0f, false};
    
    if (vis_normalized <= 0.0f) {
        result.valid = false;
        return result;
    }
    
    result.mpsas = sqmOffsetBase - sqmMagnitude * logf(vis_normalized) + calibrationOffset;
    result.valid = true;
    
    return result;
}

/**
 * Starší kompatibilní funkce - převede osvětlení (Lux) na jas oblohy (mag/arcsec2)
 * (Používá se, pokud máš lux místo raw hodnot)
 * 
 * @param lux Naměřená hodnota v luxech
 * @param lensOffset Offset konstanta (typicky 8.5265)
 * 
 * @return Hodnota v mag/arcsec2
 */
inline double convert_lux_to_sqm(double lux, double lensOffset = 8.5265) {
    // Ošetření nuly a záporných čísel (logaritmus nuly není definován)
    if (lux <= 0.000000001) {
        return 23.0;  // SQM_DARK_CAP
    }
    
    // Vzorec: SQM = Offset - 2.5 * log10(Lux)
    double sqm = lensOffset - (2.5 * log10(lux));
    
    return sqm;
}

#endif // SQM_UTILS_H

/**
 * PŘÍKLAD POUŽITÍ:
 * 
 * V kódu, kdy máš raw hodnoty z TSL2591 senzoru:
 * 
 *   uint16_t ir_raw = lum >> 16;
 *   uint16_t full_raw = lum & 0xFFFF;
 *   float gain_value = config.getSqmOffsetBase();  // nebo 25.0 apod.
 *   float integration_ms = 300.0;  // z TSL2591
 *   uint8_t niter = 1;  // počet měření pro součítání
 * 
 *   SQMResult result = calculate_sqm_from_raw(
 *       ir_raw, 
 *       full_raw, 
 *       gain_value,
 *       integration_ms,
 *       niter,
 *       config.getSqmOffsetBase(),      // 12.6
 *       config.getSqmMagnitudeConst(),  // 1.086
 *       0.0  // calibrationOffset
 *   );
 * 
 *   if (result.valid) {
 *       Serial.print("SQM: ");
 *       Serial.print(result.mpsas, 2);
 *       Serial.print(" +/- ");
 *       Serial.println(result.dmpsas, 3);
 *   } else {
 *       Serial.println("Invalid measurement");
 *   }
 */

