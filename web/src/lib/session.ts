/**
 * Živá relace: přijímá řádky ze senzoru, drží poslední hodnoty a historii
 * od připojení ve stejném datovém modelu, jaký se čte z HDF5 logů.
 */
import type { CloudMetaMsg, CloudMsg, HelloMsg, HygroMsg, LightMsg } from './protocol';
import { parseLine } from './protocol';
import type { CloudData, Dataset, LightData, SkyData } from './types';
import { emptyCloud, emptyDataset, emptyLight, emptySky } from './types';

/** ~24 h skalárních hodnot při periodě 2 s. */
const MAX_POINTS = 43_200;
/** ~6 h teplotních map na senzor při periodě 2 s (≈33 MB na senzor). */
const MAX_FRAMES = 10_800;
const MAX_LOG_LINES = 400;

export interface LogLine {
  id: number;
  time: number;
  kind: 'rx' | 'tx' | 'info';
  text: string;
}

export interface LatestFrame {
  time: number;
  rows: number;
  cols: number;
  pixels: Float32Array;
}

export interface Latest {
  hygro: (HygroMsg & { time: number }) | null;
  light: Map<number, LightMsg & { time: number }>;
  cloud: Map<number, CloudMsg & { time: number }>;
  meta: Map<number, CloudMetaMsg & { time: number }>;
  frames: Map<number, LatestFrame>;
}

function emptyLatest(): Latest {
  return { hygro: null, light: new Map(), cloud: new Map(), meta: new Map(), frames: new Map() };
}

function trim(columns: unknown[][], limit: number): void {
  const length = columns[0].length;
  if (length <= limit) return;
  // Odřezává se po větších kusech, aby splice neběžel při každém vzorku.
  const drop = length - limit + Math.floor(limit / 10);
  for (const column of columns) column.splice(0, drop);
}

export class LiveSession {
  data: Dataset = emptyDataset('Živý záznam');
  latest: Latest = emptyLatest();
  device: HelloMsg | null = null;
  log: LogLine[] = [];
  /** Počet přijatých platných datových zpráv od posledního vymazání. */
  messageCount = 0;
  /** Počet řádků začínajících `$`, které se nepodařilo zpracovat. */
  errorCount = 0;
  lastMessageAt: number | null = null;
  startedAt: number | null = null;
  /** Roste s každou změnou historie — klíč pro překreslení grafů. */
  version = 0;

  private listeners = new Set<() => void>();
  private notifyTimer: ReturnType<typeof setTimeout> | null = null;
  private logId = 0;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getVersion = (): number => this.version;

  private touch(): void {
    this.version++;
    if (this.notifyTimer) return;
    // Zprávy chodí v dávkách; UI stačí překreslit nejvýš 5× za sekundu.
    this.notifyTimer = setTimeout(() => {
      this.notifyTimer = null;
      this.listeners.forEach((listener) => listener());
    }, 200);
  }

  addLog(kind: LogLine['kind'], text: string, time = Date.now()): void {
    this.log.push({ id: ++this.logId, time, kind, text });
    if (this.log.length > MAX_LOG_LINES) this.log.splice(0, this.log.length - MAX_LOG_LINES);
    this.touch();
  }

  /** Smaže historii; identita zařízení zůstává (je to stále stejné připojení). */
  clear(): void {
    this.data = emptyDataset('Živý záznam');
    this.latest = emptyLatest();
    this.messageCount = 0;
    this.errorCount = 0;
    this.startedAt = null;
    this.touch();
  }

  private cloud(id: number): CloudData {
    const name = `cloud${id}`;
    let cloud = this.data.clouds.find((c) => c.name === name);
    if (!cloud) {
      cloud = emptyCloud(name);
      this.data.clouds.push(cloud);
      this.data.clouds.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
    }
    return cloud;
  }

  private light(channel: number): LightData {
    const name = `light${channel}`;
    let light = this.data.lights.find((l) => l.name === name);
    if (!light) {
      light = emptyLight(name, true);
      this.data.lights.push(light);
      this.data.lights.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
    }
    return light;
  }

  private sky(id: number, rows: number, cols: number): SkyData {
    const name = `sky${id}`;
    let sky = this.data.skies.find((s) => s.name === name);
    if (!sky) {
      sky = emptySky(name, rows, cols);
      this.data.skies.push(sky);
      this.data.skies.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
    }
    return sky;
  }

  ingestLine(line: string, now = Date.now()): void {
    const msg = parseLine(line);
    if (!msg) {
      if (line.trim().startsWith('$')) {
        this.errorCount++;
        this.touch();
      }
      return;
    }

    if (msg.type === 'comment') {
      this.addLog('rx', `# ${msg.text}`, now);
      return;
    }

    this.messageCount++;
    this.lastMessageAt = now;
    this.startedAt ??= now;

    switch (msg.type) {
      case 'hello':
        this.device = msg;
        this.addLog('rx', line.trim(), now);
        break;

      case 'hygro': {
        this.latest.hygro = { ...msg, time: now };
        if (msg.valid) {
          const h = this.data.hygro;
          h.t.push(now);
          h.temp.push(msg.temperature);
          h.hum.push(msg.humidity);
          trim([h.t, h.temp, h.hum], MAX_POINTS);
        }
        break;
      }

      case 'light': {
        this.latest.light.set(msg.channel, { ...msg, time: now });
        const l = this.light(msg.channel);
        l.t.push(now);
        l.full.push(msg.fullRaw);
        l.ir.push(msg.irRaw);
        l.gain.push(msg.gain);
        l.expo.push(msg.integrationMs);
        l.lux!.push(msg.lux);
        l.sqm!.push(msg.sqm);
        trim([l.t, l.full, l.ir, l.gain, l.expo, l.lux!, l.sqm!], MAX_POINTS);
        break;
      }

      case 'cloud_meta':
        this.latest.meta.set(msg.sensorId, { ...msg, time: now });
        break;

      case 'cloud': {
        this.latest.cloud.set(msg.sensorId, { ...msg, time: now });
        const c = this.cloud(msg.sensorId);
        c.t.push(now);
        c.center.push(msg.center);
        c.tl.push(msg.tl);
        c.tr.push(msg.tr);
        c.bl.push(msg.bl);
        c.br.push(msg.br);
        c.vdd.push(this.latest.meta.get(msg.sensorId)?.vdd ?? NaN);
        trim([c.t, c.center, c.tl, c.tr, c.bl, c.br, c.vdd], MAX_POINTS);
        break;
      }

      case 'thrmap': {
        this.latest.frames.set(msg.sensorId, { time: now, rows: msg.rows, cols: msg.cols, pixels: msg.pixels });
        const s = this.sky(msg.sensorId, msg.rows, msg.cols);
        if (s.rows === msg.rows && s.cols === msg.cols) {
          s.t.push(now);
          s.temp.push(this.latest.meta.get(msg.sensorId)?.ta ?? NaN);
          s.frames.push(msg.pixels);
          trim([s.t, s.temp, s.frames], MAX_FRAMES);
        }
        break;
      }
    }
    this.touch();
  }
}
