/**
 * Společný datový model pro živá data ze sériové linky i pro HDF5 logy.
 * Vše je sloupcové (pole časů + pole hodnot), časy jsou Unix ms.
 */

export interface CloudData {
  /** Název skupiny v HDF5, např. "cloud1". */
  name: string;
  t: number[];
  center: number[];
  tl: number[];
  tr: number[];
  bl: number[];
  br: number[];
  vdd: number[];
}

export interface HygroData {
  t: number[];
  temp: number[];
  hum: number[];
}

export interface LightData {
  /** Název skupiny v HDF5: "light" (jednokanálové logy) nebo "light0"/"light1". */
  name: string;
  t: number[];
  full: number[];
  ir: number[];
  gain: number[];
  expo: number[];
  /** Lux a SQM spočtené přímo zařízením — jen u záznamů pořízených z webu. */
  lux?: number[];
  sqm?: number[];
}

export interface SkyData {
  /** Název skupiny v HDF5: "sky" (AMSKY01) nebo "sky1"/"sky2". */
  name: string;
  rows: number;
  cols: number;
  t: number[];
  /** Teplota čipu senzoru (MLX Ta) v okamžiku snímku. */
  temp: number[];
  frames: Float32Array[];
}

export interface Dataset {
  label: string;
  clouds: CloudData[];
  hygro: HygroData;
  lights: LightData[];
  skies: SkyData[];
}

export interface TimeRange {
  from: number;
  to: number;
}

export interface H5FileEntry {
  filename: string;
  url: string;
  source?: string;
}

export function emptyCloud(name: string): CloudData {
  return { name, t: [], center: [], tl: [], tr: [], bl: [], br: [], vdd: [] };
}

export function emptyLight(name: string, withDeviceValues = false): LightData {
  const light: LightData = { name, t: [], full: [], ir: [], gain: [], expo: [] };
  if (withDeviceValues) {
    light.lux = [];
    light.sqm = [];
  }
  return light;
}

export function emptySky(name: string, rows: number, cols: number): SkyData {
  return { name, rows, cols, t: [], temp: [], frames: [] };
}

export function emptyDataset(label: string): Dataset {
  return { label, clouds: [], hygro: { t: [], temp: [], hum: [] }, lights: [], skies: [] };
}

export function datasetTimeRange(data: Dataset): TimeRange | null {
  let from = Infinity;
  let to = -Infinity;
  const visit = (t: number[]) => {
    if (t.length === 0) return;
    // Časy jsou seřazené, stačí první a poslední prvek.
    if (t[0] < from) from = t[0];
    if (t[t.length - 1] > to) to = t[t.length - 1];
  };
  data.clouds.forEach((c) => visit(c.t));
  data.lights.forEach((l) => visit(l.t));
  data.skies.forEach((s) => visit(s.t));
  visit(data.hygro.t);
  return Number.isFinite(from) && Number.isFinite(to) ? { from, to } : null;
}

export function datasetIsEmpty(data: Dataset): boolean {
  return datasetTimeRange(data) === null;
}
