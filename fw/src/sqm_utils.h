#ifndef SQM_UTILS_H
#define SQM_UTILS_H

#include <math.h>

/**
 * Teoretický výpočet konstanty (Python derivation):
 * ------------------------------------------------
 * import math
 *
 * # 1. Vstupní parametry
 * lens_fov_deg = 10.0
 * standard_mag_zeropoint = 12.58
 *
 * # 2. Výpočet prostorového úhlu (Omega) pro kužel 10 stupňů
 * # Omega = 2 * PI * (1 - cos(FOV / 2))
 * alpha_rad = math.radians(lens_fov_deg)
 * omega = 2 * math.pi * (1 - math.cos(alpha_rad / 2))
 * # omega vychází cca 0.023909 sr
 *
 * # 3. Sloučení konstant do jedné
 * # Základní vzorec: SQM = 12.58 - 2.5 * log10(Lux / Omega)
 * # Rozpad: SQM = 12.58 - 2.5 * log10(Lux) + 2.5 * log10(Omega)
 * # Konstanta (OFFSET) = 12.58 + 2.5 * log10(Omega)
 *
 * offset = standard_mag_zeropoint + (2.5 * math.log10(omega))
 * # offset vychází cca 8.5265
 */

// Předvypočítaná konstanta pro 10° čočku
// Teoreticky odvozená hodnota. V praxi zde pravděpodobně přičteš/odečteš
// malou hodnotu po kalibraci s reálným SQM metrem.
#define LENS_OFFSET_CONSTANT 8.5265

// Maximální hodnota SQM (úplná tma), kterou chceme vrátit,
// pokud senzor naměří 0 nebo zápornou hodnotu (šum/chyba).
// Nejtmanvější obloha na Zemi má cca 22.0 mag/arcsec2.
#define SQM_DARK_CAP 23.0

/**
 * Převede osvětlení (Lux) na jas oblohy (mag/arcsec2)
 * @param lux Naměřená hodnota v luxech (očekává se double pro přesnost)
 * @return Hodnota v mag/arcsec2
 */
double convert_lux_to_sqm(double lux) {
    // 1. Ošetření nuly a záporných čísel (logaritmus nuly není definován)
    // Pokud je lux velmi malý, považujeme to za "absolutní tmu" v rámci možností senzoru.
    if (lux <= 0.000000001) {
        return SQM_DARK_CAP;
    }

    // 2. Výpočet SQM
    // Vzorec: SQM = Konstanta - 2.5 * log10(Lux)
    double sqm = LENS_OFFSET_CONSTANT - (2.5 * log10(lux));

    return sqm;
}

#endif // SQM_UTILS_H
