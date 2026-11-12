import type { SkyData } from './types';

/** Barevné palety teplotní mapy; první je výchozí (stejná jako v původním prohlížeči). */
export const PALETTES = {
  thermal: { label: 'Thermal', colors: ['#000000', '#6a0dad', '#dd0000', '#ff8c00', '#ffffff'] },
  inferno: { label: 'Inferno', colors: ['#000004', '#420a68', '#932667', '#dd513a', '#fca50a', '#fcffa4'] },
  viridis: { label: 'Viridis', colors: ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725'] },
  coolwarm: { label: 'Blue–red', colors: ['#3b4cc0', '#8db0fe', '#dddddd', '#f4987a', '#b40426'] },
  gray: { label: 'Gray', colors: ['#000000', '#ffffff'] },
} as const;

export type PaletteName = keyof typeof PALETTES;

export function isPaletteName(value: unknown): value is PaletteName {
  return typeof value === 'string' && value in PALETTES;
}

const lutCache = new Map<PaletteName, Uint8ClampedArray>();

/** 256 položek RGBA pro rychlé barvení pixelů. */
export function paletteLut(name: PaletteName): Uint8ClampedArray {
  const cached = lutCache.get(name);
  if (cached) return cached;
  const stops = PALETTES[name].colors.map((hex) => [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ]);
  const lut = new Uint8ClampedArray(256 * 4);
  const segments = stops.length - 1;
  for (let i = 0; i < 256; i++) {
    const pos = (i / 255) * segments;
    const seg = Math.min(Math.floor(pos), segments - 1);
    const f = pos - seg;
    for (let c = 0; c < 3; c++) lut[i * 4 + c] = stops[seg][c] + (stops[seg + 1][c] - stops[seg][c]) * f;
    lut[i * 4 + 3] = 255;
  }
  lutCache.set(name, lut);
  return lut;
}

/**
 * Uspořádání snímků obou senzorů do jednoho obrazu:
 *  - `rotated`: každý snímek otočený o 90° doleva, senzory těsně vedle sebe
 *    (stejně jako amsky-viewer),
 *  - `stacked`: bez otočení, první senzor nad druhým.
 */
export type SkyLayout = 'rotated' | 'stacked';

export interface SkyTile {
  rows: number;
  cols: number;
  pixels: Float32Array | null;
}

export interface SkyComposite {
  width: number;
  height: number;
  /** Hodnoty po řádcích; NaN tam, kde senzor nemá data. */
  data: Float32Array;
  /** Rozměr jednoho senzoru ve složeném obrazu. */
  tileWidth: number;
  tileHeight: number;
  /** Převod souřadnic složeného obrazu zpět na senzor a jeho původní pixel. */
  locate(x: number, y: number): { tile: number; col: number; row: number } | null;
}

export function composeSky(tiles: SkyTile[], layout: SkyLayout): SkyComposite | null {
  if (tiles.length === 0) return null;
  const { rows, cols } = tiles[0];
  const rotated = layout === 'rotated';
  const tileWidth = rotated ? rows : cols;
  const tileHeight = rotated ? cols : rows;
  const width = rotated ? tileWidth * tiles.length : tileWidth;
  const height = rotated ? tileHeight : tileHeight * tiles.length;
  const data = new Float32Array(width * height).fill(NaN);

  const locate = (x: number, y: number) => {
    if (x < 0 || y < 0 || x >= width || y >= height) return null;
    const tile = rotated ? Math.floor(x / tileWidth) : Math.floor(y / tileHeight);
    const lx = rotated ? x - tile * tileWidth : x;
    const ly = rotated ? y : y - tile * tileHeight;
    // Otočení o 90° doleva (np.rot90, k=1): out[i][j] = in[j][cols-1-i].
    return rotated ? { tile, row: lx, col: cols - 1 - ly } : { tile, row: ly, col: lx };
  };

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const at = locate(x, y)!;
      const tile = tiles[at.tile];
      // Snímek s jiným rozlišením nelze do společné mřížky zařadit.
      if (!tile.pixels || tile.rows !== rows || tile.cols !== cols) continue;
      data[y * width + x] = tile.pixels[at.row * cols + at.col];
    }
  }
  return { width, height, data, tileWidth, tileHeight, locate };
}

export function centerAverage(data: Float32Array, rows: number, cols: number): number {
  const r0 = Math.floor((rows - 2) / 2);
  const c0 = Math.floor((cols - 2) / 2);
  let sum = 0;
  for (let r = r0; r < r0 + 2; r++) {
    for (let c = c0; c < c0 + 2; c++) sum += data[r * cols + c];
  }
  return sum / 4;
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const index = (p / 100) * (sorted.length - 1);
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  if (lower === upper) return sorted[lower];
  const w = index - lower;
  return sorted[lower] * (1 - w) + sorted[upper] * w;
}

export interface ColorRange {
  min: number;
  max: number;
}

/**
 * Rozsah barevné škály přes všechny snímky: 5. percentil minim a 95. percentil
 * maxim jednotlivých snímků, aby škálu nerozhodil ojedinělý úlet.
 */
export function skyColorRange(skies: SkyData[]): ColorRange {
  const mins: number[] = [];
  const maxs: number[] = [];
  for (const sky of skies) {
    for (const frame of sky.frames) {
      let lo = Infinity;
      let hi = -Infinity;
      for (let i = 0; i < frame.length; i++) {
        const v = frame[i];
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
      if (Number.isFinite(lo)) mins.push(lo);
      if (Number.isFinite(hi)) maxs.push(hi);
    }
  }
  if (mins.length === 0 || maxs.length === 0) return { min: 0, max: 1 };
  mins.sort((a, b) => a - b);
  maxs.sort((a, b) => a - b);
  const min = percentile(mins, 5);
  const max = percentile(maxs, 95);
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { min: 0, max: 1 };
  if (min === max) return { min: min - 0.5, max: max + 0.5 };
  return { min, max };
}

/** Index posledního prvku seřazeného pole `t`, který je ≤ `time` (jinak 0). */
export function indexAtTime(t: number[], time: number): number {
  let lo = 0;
  let hi = t.length - 1;
  if (hi < 0) return -1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (t[mid] <= time) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}
