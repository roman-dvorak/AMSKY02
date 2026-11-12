/**
 * Čtení a zápis HDF5 logů AMSKY v prohlížeči (h5wasm).
 *
 * Rozložení odpovídá `HDF5Logger` v sw/amsky_viewer.py. Čtení je tolerantní
 * ke všem generacím logů:
 *   AMSKY01:           /sky, /light, /hygro
 *   AMSKY02 (starší):  /sky1 /sky2, /cloud1 /cloud2, /light, /hygro
 *   AMSKY02:           /sky1 /sky2, /cloud1 /cloud2, /light0 /light1, /hygro
 * Chybějící skupina nebo dataset se přeskočí, soubor se kvůli tomu neodmítne.
 */
import type { Dataset as H5Dataset, File as H5File, Group as H5Group } from 'h5wasm';
import type { CloudData, Dataset, LightData, SkyData } from './types';
import { emptyDataset } from './types';

type H5Api = typeof import('h5wasm').default;
type H5FS = { writeFile(path: string, data: Uint8Array): void; readFile(path: string): Uint8Array; unlink(path: string): void };

let apiPromise: Promise<{ h5: H5Api; fs: H5FS }> | null = null;

/** h5wasm (≈4 MB včetně wasm) se stahuje až při první práci se souborem. */
function loadApi(): Promise<{ h5: H5Api; fs: H5FS }> {
  if (!apiPromise) {
    apiPromise = (async () => {
      const mod = await import('h5wasm');
      const h5 = mod.default;
      const module = await h5.ready;
      const fs = (module as unknown as { FS?: H5FS }).FS;
      if (!fs) throw new Error('h5wasm filesystem není dostupný');
      return { h5, fs };
    })();
    apiPromise.catch(() => (apiPromise = null));
  }
  return apiPromise;
}

let fileCounter = 0;

const SIGNATURE = [0x89, 0x48, 0x44, 0x46, 0x0d, 0x0a, 0x1a, 0x0a];

/** Signatura HDF5 leží na offsetu 0, případně 512·2ⁿ za uživatelským blokem. */
function isHdf5(bytes: Uint8Array): boolean {
  for (let offset = 0; offset + SIGNATURE.length <= bytes.length; offset = offset === 0 ? 512 : offset * 2) {
    if (SIGNATURE.every((byte, i) => bytes[offset + i] === byte)) return true;
  }
  return false;
}

function childNames(group: H5Group, pattern: RegExp): string[] {
  return group
    .keys()
    .filter((key) => pattern.test(key))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

function dataset(file: H5File, path: string): H5Dataset | null {
  try {
    const entity = file.get(path) as unknown as { value?: unknown; shape?: unknown } | null;
    return entity && 'shape' in entity && entity.shape !== undefined ? (entity as unknown as H5Dataset) : null;
  } catch {
    return null;
  }
}

function timesMs(file: H5File, path: string): number[] | null {
  const raw = dataset(file, path)?.value;
  if (raw instanceof BigInt64Array || raw instanceof BigUint64Array) {
    const out = new Array<number>(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = Number(raw[i] / 1_000_000n);
    return out;
  }
  if (ArrayBuffer.isView(raw) || Array.isArray(raw)) {
    return Array.from(raw as ArrayLike<number | bigint>, (v) => Math.floor(Number(v) / 1e6));
  }
  return null;
}

function floats(file: H5File, path: string): number[] | null {
  const raw = dataset(file, path)?.value;
  if (ArrayBuffer.isView(raw) || Array.isArray(raw)) {
    return Array.from(raw as ArrayLike<number | bigint>, (v) => Number(v));
  }
  return null;
}

/** Řada stejné délky jako časová osa; chybějící dataset se doplní NaN. */
function column(file: H5File, path: string, length: number): number[] {
  const values = floats(file, path) ?? [];
  const out = new Array<number>(length);
  for (let i = 0; i < length; i++) out[i] = i < values.length ? values[i] : NaN;
  return out;
}

function readCloud(file: H5File, name: string): CloudData | null {
  const t = timesMs(file, `${name}/time`);
  if (!t) return null;
  const n = Math.min(t.length, floats(file, `${name}/center`)?.length ?? 0);
  const col = (key: string) => column(file, `${name}/${key}`, n);
  return {
    name,
    t: t.slice(0, n),
    center: col('center'),
    tl: col('tl'),
    tr: col('tr'),
    bl: col('bl'),
    br: col('br'),
    vdd: col('vdd'),
  };
}

function readLight(file: H5File, name: string): LightData | null {
  const t = timesMs(file, `${name}/time`);
  const full = floats(file, `${name}/all`);
  const ir = floats(file, `${name}/ir`);
  if (!t || !full || !ir) return null;
  const n = Math.min(t.length, full.length, ir.length);
  const light: LightData = {
    name,
    t: t.slice(0, n),
    full: full.slice(0, n),
    ir: ir.slice(0, n),
    gain: column(file, `${name}/gain`, n),
    expo: column(file, `${name}/expo`, n),
  };
  const lux = floats(file, `${name}/lux`);
  const sqm = floats(file, `${name}/sqm`);
  if (lux && sqm && lux.length >= n && sqm.length >= n) {
    light.lux = lux.slice(0, n);
    light.sqm = sqm.slice(0, n);
  }
  return light;
}

function readSky(file: H5File, name: string): SkyData | null {
  const t = timesMs(file, `${name}/time`);
  const data = dataset(file, `${name}/data`);
  const shape = data?.shape;
  if (!t || !data || !shape || shape.length !== 3) return null;
  const [count, rows, cols] = shape;
  const raw = data.value;
  if (!(raw instanceof Float32Array)) return null;
  const n = Math.min(t.length, count);
  const stride = rows * cols;
  const frames = new Array<Float32Array>(n);
  // slice() kopíruje — snímky nesmí ukazovat do paměti wasm, která se uvolní.
  for (let i = 0; i < n; i++) frames[i] = raw.slice(i * stride, (i + 1) * stride);
  return { name, rows, cols, t: t.slice(0, n), temp: column(file, `${name}/temp`, n), frames };
}

export async function parseH5(filename: string, input: ArrayBuffer | Uint8Array): Promise<Dataset> {
  const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
  // h5wasm u neplatného souboru nevyhodí výjimku při otevření, ale až
  // nesrozumitelně při čtení — proto kontrola předem.
  if (!isHdf5(bytes)) throw new Error(`${filename}: soubor není platné HDF5`);
  const { h5, fs } = await loadApi();
  const path = `/in_${++fileCounter}.h5`;
  fs.writeFile(path, bytes);
  let file: H5File | null = null;
  try {
    file = new h5.File(path, 'r');
    const result = emptyDataset(filename);
    for (const name of childNames(file, /^cloud\d*$/)) {
      const cloud = readCloud(file, name);
      if (cloud) result.clouds.push(cloud);
    }
    for (const name of childNames(file, /^light\d*$/)) {
      const light = readLight(file, name);
      if (light) result.lights.push(light);
    }
    for (const name of childNames(file, /^sky\d*$/)) {
      const sky = readSky(file, name);
      if (sky) result.skies.push(sky);
    }
    const hygroT = timesMs(file, 'hygro/time');
    if (hygroT) {
      const n = Math.min(hygroT.length, floats(file, 'hygro/temp')?.length ?? 0);
      result.hygro = {
        t: hygroT.slice(0, n),
        temp: column(file, 'hygro/temp', n),
        hum: column(file, 'hygro/hum', n),
      };
    }
    return result;
  } finally {
    try {
      file?.close();
    } catch {
      /* ignore */
    }
    try {
      fs.unlink(path);
    } catch {
      /* ignore */
    }
  }
}

function nsTimes(t: number[]): BigInt64Array {
  const out = new BigInt64Array(t.length);
  for (let i = 0; i < t.length; i++) out[i] = BigInt(Math.round(t[i])) * 1_000_000n;
  return out;
}

function writeColumns(group: H5Group, t: number[], columns: Record<string, number[]>): void {
  // Prázdný dataset vytvořit nelze bez explicitního tvaru — vždy ho uvádíme.
  group.create_dataset({ name: 'time', data: nsTimes(t), shape: [t.length], dtype: '<q' });
  for (const [name, values] of Object.entries(columns)) {
    group.create_dataset({ name, data: Float32Array.from(values), shape: [t.length], dtype: '<f' });
  }
}

/** Zapíše dataset do HDF5 ve stejném rozložení jako Python logger. */
export async function writeH5(data: Dataset): Promise<Uint8Array> {
  const { h5, fs } = await loadApi();
  const path = `/out_${++fileCounter}.h5`;
  const file = new h5.File(path, 'w');
  try {
    for (const sky of data.skies) {
      const group = file.create_group(sky.name);
      const stride = sky.rows * sky.cols;
      const cube = new Float32Array(sky.frames.length * stride);
      sky.frames.forEach((frame, i) => cube.set(frame, i * stride));
      group.create_dataset({ name: 'data', data: cube, shape: [sky.frames.length, sky.rows, sky.cols], dtype: '<f' });
      writeColumns(group, sky.t, { temp: sky.temp });
    }
    writeColumns(file.create_group('hygro'), data.hygro.t, { temp: data.hygro.temp, hum: data.hygro.hum });
    for (const light of data.lights) {
      const columns: Record<string, number[]> = { all: light.full, ir: light.ir, gain: light.gain, expo: light.expo };
      if (light.lux && light.sqm) {
        columns.lux = light.lux;
        columns.sqm = light.sqm;
      }
      writeColumns(file.create_group(light.name), light.t, columns);
    }
    for (const cloud of data.clouds) {
      writeColumns(file.create_group(cloud.name), cloud.t, {
        tl: cloud.tl,
        tr: cloud.tr,
        bl: cloud.bl,
        br: cloud.br,
        center: cloud.center,
        vdd: cloud.vdd,
      });
    }
    file.flush();
  } finally {
    file.close();
  }
  try {
    return fs.readFile(path).slice();
  } finally {
    fs.unlink(path);
  }
}
