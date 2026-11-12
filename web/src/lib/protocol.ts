/**
 * Parser sériového protokolu AMSKY (viz README v kořeni repozitáře).
 *
 * Datové řádky začínají `$`, řádky s `#` jsou komentáře pro člověka.
 * Podporuje AMSKY02 (indexované zprávy, mapa 32×24) i starší AMSKY01
 * (`$light` bez čísla kanálu, mapa 16×12).
 */

export interface HelloMsg {
  type: 'hello';
  model: string;
  serial: string;
  fwVersion: string;
  gitHash: string;
  gitBranch: string;
}

export interface LightMsg {
  type: 'light';
  channel: number;
  lux: number;
  fullRaw: number;
  irRaw: number;
  gain: number;
  integrationMs: number;
  sqm: number;
}

export interface CloudMsg {
  type: 'cloud';
  sensorId: number;
  tl: number;
  tr: number;
  bl: number;
  br: number;
  center: number;
}

export interface CloudMetaMsg {
  type: 'cloud_meta';
  sensorId: number;
  vdd: number;
  ta: number;
}

export interface HygroMsg {
  type: 'hygro';
  temperature: number;
  humidity: number;
  dewPoint: number;
  /** Firmware posílá -999, když čidlo neodpovídá. */
  valid: boolean;
}

export interface ThrmapMsg {
  type: 'thrmap';
  sensorId: number;
  rows: number;
  cols: number;
  pixels: Float32Array;
}

export interface CommentMsg {
  type: 'comment';
  text: string;
}

export type AmskyMessage =
  | HelloMsg
  | LightMsg
  | CloudMsg
  | CloudMetaMsg
  | HygroMsg
  | ThrmapMsg
  | CommentMsg;

const MAP_SHAPES: Record<number, { rows: number; cols: number }> = {
  768: { rows: 24, cols: 32 }, // MLX90642 (AMSKY02)
  192: { rows: 12, cols: 16 }, // MLX90641 (AMSKY01)
};

function numbers(parts: string[], from: number, count: number): number[] | null {
  if (parts.length < from + count) return null;
  const out: number[] = [];
  for (let i = from; i < from + count; i++) {
    const value = Number(parts[i]);
    if (parts[i].trim() === '' || Number.isNaN(value)) return null;
    out.push(value);
  }
  return out;
}

/** "25", "25x" → 25; "600", "600ms" → 600. */
function leadingNumber(text: string): number {
  const value = parseFloat(text);
  return Number.isFinite(value) ? value : NaN;
}

/** Vrací `null` pro prázdný, neznámý nebo poškozený řádek. */
export function parseLine(raw: string): AmskyMessage | null {
  const line = raw.trim();
  if (!line) return null;
  if (line.startsWith('#')) return { type: 'comment', text: line.slice(1).trim() };
  if (!line.startsWith('$')) return null;

  const parts = line.split(',');
  switch (parts[0]) {
    case '$HELLO':
      if (parts.length < 3) return null;
      return {
        type: 'hello',
        model: parts[1],
        serial: parts[2],
        fwVersion: parts[3] ?? '',
        gitHash: parts[4] ?? '',
        gitBranch: parts[5] ?? '',
      };

    case '$light': {
      // AMSKY02: $light,<ch>,<lux>,<full>,<ir>,<gain>,<itime>,<sqm>
      // AMSKY01: $light,<lux>,<full>,<ir>,<gain>,<itime>,<sqm>
      const indexed = parts.length >= 8;
      const o = indexed ? 2 : 1;
      if (parts.length < o + 6) return null;
      const head = numbers(parts, o, 3);
      const channel = indexed ? Number(parts[1]) : 0;
      const gain = leadingNumber(parts[o + 3]);
      const integrationMs = leadingNumber(parts[o + 4]);
      const sqm = Number(parts[o + 5]);
      if (!head || !Number.isInteger(channel) || Number.isNaN(gain) || Number.isNaN(integrationMs)) {
        return null;
      }
      // Firmware AMSKY02 posílá osvětlení jako celé číslo v mikroluxech,
      // starší firmware jako desetinné číslo v luxech.
      const lux = parts[o].includes('.') ? head[0] : head[0] / 1e6;
      return {
        type: 'light',
        channel,
        lux,
        fullRaw: head[1],
        irRaw: head[2],
        gain,
        integrationMs,
        sqm: Number.isFinite(sqm) ? sqm : NaN,
      };
    }

    case '$cloud': {
      const v = numbers(parts, 1, 6);
      if (!v) return null;
      return { type: 'cloud', sensorId: v[0], tl: v[1], tr: v[2], bl: v[3], br: v[4], center: v[5] };
    }

    case '$cloud_meta': {
      const v = numbers(parts, 1, 3);
      if (!v) return null;
      return { type: 'cloud_meta', sensorId: v[0], vdd: v[1], ta: v[2] };
    }

    case '$hygro': {
      const v = numbers(parts, 1, 3);
      if (!v) return null;
      return {
        type: 'hygro',
        temperature: v[0],
        humidity: v[1],
        dewPoint: v[2],
        valid: v[0] > -900 && v[1] > -900,
      };
    }

    case '$thrmap': {
      const sensorId = Number(parts[1]);
      const count = parts.length - 2;
      const shape = MAP_SHAPES[count];
      // Neúplný řádek (useknutý při připojení) nemá žádnou ze známých délek.
      if (!shape || !Number.isInteger(sensorId)) return null;
      const pixels = new Float32Array(count);
      for (let i = 0; i < count; i++) {
        const value = Number(parts[i + 2]);
        if (Number.isNaN(value)) return null;
        pixels[i] = value;
      }
      return { type: 'thrmap', sensorId, rows: shape.rows, cols: shape.cols, pixels };
    }

    default:
      return null;
  }
}
