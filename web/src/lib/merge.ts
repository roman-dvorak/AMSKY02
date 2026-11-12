import type { CloudData, Dataset, HygroData, LightData, SkyData } from './types';
import { datasetTimeRange, emptyDataset } from './types';

type Columns = { t: number[] };

/** Spojí sloupcové řady za sebe; pokud výsledek není v čase seřazený, seřadí ho. */
function concatColumns<T extends Columns>(parts: T[], keys: (keyof T & string)[]): T {
  const out = { ...parts[0] } as Record<string, unknown>;
  for (const key of keys) {
    const present = parts.every((part) => Array.isArray(part[key]));
    // Volitelný sloupec (lux/sqm ze zařízení) zůstane jen tehdy, mají-li ho všechny části.
    if (!present) {
      delete out[key];
      continue;
    }
    out[key] = parts.length === 1 ? parts[0][key] : parts.flatMap((part) => part[key] as unknown[]);
  }
  const t = out.t as number[];
  let sorted = true;
  for (let i = 1; i < t.length; i++) {
    if (t[i] < t[i - 1]) {
      sorted = false;
      break;
    }
  }
  if (!sorted) {
    const order = t.map((_, i) => i).sort((a, b) => t[a] - t[b]);
    for (const key of keys) {
      const column = out[key] as unknown[] | undefined;
      if (column) out[key] = order.map((i) => column[i]);
    }
  }
  return out as unknown as T;
}

function groupByName<T extends { name: string }>(items: T[]): Map<string, T[]> {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const list = groups.get(item.name);
    if (list) list.push(item);
    else groups.set(item.name, [item]);
  }
  return groups;
}

const byName = (a: { name: string }, b: { name: string }) =>
  a.name.localeCompare(b.name, undefined, { numeric: true });

/** Sloučí několik (typicky hodinových) souborů do jedné časové řady. */
export function mergeDatasets(files: Dataset[]): Dataset {
  if (files.length === 0) return emptyDataset('');
  if (files.length === 1) return files[0];

  const sorted = [...files].sort(
    (a, b) => (datasetTimeRange(a)?.from ?? Infinity) - (datasetTimeRange(b)?.from ?? Infinity),
  );
  const result = emptyDataset(sorted.map((f) => f.label).join(', '));
  const device = sorted.find((f) => f.device)?.device;
  if (device) result.device = device;

  for (const parts of groupByName(sorted.flatMap((f) => f.clouds)).values()) {
    result.clouds.push(concatColumns<CloudData>(parts, ['t', 'center', 'tl', 'tr', 'bl', 'br', 'vdd']));
  }
  for (const parts of groupByName(sorted.flatMap((f) => f.lights)).values()) {
    result.lights.push(concatColumns<LightData>(parts, ['t', 'full', 'ir', 'gain', 'expo', 'lux', 'sqm']));
  }
  for (const parts of groupByName(sorted.flatMap((f) => f.skies)).values()) {
    // Soubory z různých generací senzoru mají jiné rozlišení mapy; nelze je
    // míchat v jedné řadě, platí rozlišení prvního souboru.
    const { rows, cols } = parts[0];
    const same = parts.filter((p) => p.rows === rows && p.cols === cols);
    result.skies.push(concatColumns<SkyData>(same, ['t', 'temp', 'frames']));
  }
  result.hygro = concatColumns<HygroData>(
    sorted.map((f) => f.hygro),
    ['t', 'temp', 'hum'],
  );

  result.clouds.sort(byName);
  result.lights.sort(byName);
  result.skies.sort(byName);
  return result;
}
