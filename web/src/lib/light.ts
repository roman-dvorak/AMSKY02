import type { LightData } from './types';

/** Stejná kalibrační konstanta jako v AMSKY01 (light_lux_calc). */
export const LIGHT_LUX_SCALE = 40.8;

/**
 * Převod kalibrovaného lux na jas oblohy v mag/arcsec² (SQM).
 * Předpoklad: lux z měření zenitní oblohy, L = lux / π.
 */
export const SQM_ZEROPOINT = 14.2;

export function calibrateLightLux(raw: number, gain: number, expo: number): number {
  if (gain <= 0 || expo <= 0) return 0;
  return (raw / (gain * expo)) * LIGHT_LUX_SCALE;
}

export function luxToSqm(lux: number): number {
  if (!(lux > 0)) return NaN;
  return SQM_ZEROPOINT - 2.5 * Math.log10(lux);
}

export interface LightSeries {
  /** true = hodnoty spočítalo zařízení, false = přepočet z raw hodnot v logu. */
  fromDevice: boolean;
  luxAll: number[];
  luxIr: number[] | null;
  sqmAll: number[];
  sqmIr: number[] | null;
}

/**
 * Odvozené řady pro grafy. Záznam pořízený z webu nese lux a SQM tak, jak je
 * spočítal firmware (včetně kalibrace `sqm_offset`); starší HDF5 logy mají jen
 * raw hodnoty, ty se přepočítají stejně jako v původním prohlížeči.
 */
export function lightSeries(light: LightData): LightSeries {
  if (light.lux && light.sqm && light.lux.length === light.t.length) {
    return {
      fromDevice: true,
      luxAll: light.lux,
      luxIr: null,
      sqmAll: light.sqm.map((v) => (v > 0 ? v : NaN)),
      sqmIr: null,
    };
  }
  const luxAll = light.full.map((raw, i) => calibrateLightLux(raw, light.gain[i], light.expo[i]));
  const luxIr = light.ir.map((raw, i) => calibrateLightLux(raw, light.gain[i], light.expo[i]));
  return {
    fromDevice: false,
    luxAll,
    luxIr,
    sqmAll: luxAll.map(luxToSqm),
    sqmIr: luxIr.map(luxToSqm),
  };
}
