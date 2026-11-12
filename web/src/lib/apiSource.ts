/**
 * Živá data z HTTP JSON API Python vieweru (`amsky-viewer --api`, /data.json).
 *
 * API vrací vždy jen poslední hodnoty bez časů jednotlivých měření. Snímek se
 * proto převádí na řádky sériového protokolu a dál jde stejnou cestou jako
 * data ze sériové linky; sekce, která se od minulého dotazu nezměnila, se
 * znovu neposílá, aby v historii nevznikaly duplicitní body.
 */

export const DEFAULT_API_URL = 'http://localhost:8080/data.json';

/** "localhost:8080" → "http://localhost:8080/data.json". */
export function normalizeApiUrl(input: string): string {
  let text = input.trim();
  if (!text) return DEFAULT_API_URL;
  if (!/^https?:\/\//i.test(text)) text = `http://${text}`;
  const url = new URL(text);
  if (url.pathname === '' || url.pathname === '/') url.pathname = '/data.json';
  return url.toString();
}

type Section = Record<string, unknown>;

function section(value: unknown): Section | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Section) : null;
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function allNumbers(values: unknown[]): number[] | null {
  const out = values.map(num);
  return out.every((v) => v !== null) ? (out as number[]) : null;
}

/** Drží otisk naposledy odeslaných sekcí mezi jednotlivými dotazy. */
export class SnapshotConverter {
  private seen = new Map<string, string>();

  private changed(key: string, value: unknown): boolean {
    const print = JSON.stringify(value);
    if (this.seen.get(key) === print) return false;
    this.seen.set(key, print);
    return true;
  }

  /** Řádky protokolu pro sekce, které se od minulého snímku změnily. */
  toLines(snapshot: unknown): string[] {
    const data = section(snapshot);
    if (!data) return [];
    const lines: string[] = [];

    const device = section(data.device);
    if (device && typeof device.serial_number === 'string' && this.changed('device', device)) {
      const field = (key: string) => (typeof device[key] === 'string' ? (device[key] as string) : '');
      lines.push(
        `$HELLO,${field('device_model')},${device.serial_number},${field('fw_version')},${field('git_hash')},${field('git_branch')}`,
      );
    }

    const hygro = section(data.hygro);
    const hygroValues = hygro && allNumbers([hygro.temp, hygro.rh, hygro.dew_point]);
    if (hygroValues && this.changed('hygro', hygroValues)) lines.push(`$hygro,${hygroValues.join(',')}`);

    // AMSKY02 má kanály light0/light1, starší viewer jedinou sekci "light".
    const lights: [number, Section | null][] = [
      [0, section(data.light0) ?? section(data.light)],
      [1, section(data.light1)],
    ];
    for (const [channel, light] of lights) {
      const raw = light && allNumbers([light.full, light.ir]);
      if (!light || !raw || light.gain == null || light.itime == null) continue;
      if (!this.changed(`light${channel}`, light)) continue;
      // Desetinná tečka říká parseru, že jde o luxy (firmware posílá celé µlx).
      const lux = (num(light.lux) ?? 0).toFixed(6);
      const sqm = num(light.sqm) ?? 'nan';
      lines.push(`$light,${channel},${lux},${raw[0]},${raw[1]},${String(light.gain)},${String(light.itime)},${sqm}`);
    }

    // Meta před $cloud a $thrmap: z ní se bere Vdd a teplota čipu.
    for (const id of [1, 2]) {
      const mlx = section(data[`mlx${id}`]);
      const meta = mlx && allNumbers([mlx.vdd, mlx.ta]);
      if (meta && this.changed(`mlx${id}`, meta)) lines.push(`$cloud_meta,${id},${meta.join(',')}`);
    }
    for (const id of [1, 2]) {
      const cloud = section(data[`cloud${id}`]);
      const values = cloud && allNumbers([cloud.tl, cloud.tr, cloud.bl, cloud.br, cloud.center]);
      if (values && this.changed(`cloud${id}`, values)) lines.push(`$cloud,${id},${values.join(',')}`);
    }
    for (const id of [1, 2]) {
      const map = data[`thrmap${id}`];
      if (Array.isArray(map) && map.length > 0 && this.changed(`thrmap${id}`, map)) {
        lines.push(`$thrmap,${id},${map.join(',')}`);
      }
    }
    return lines;
  }
}

/** Srozumitelnější důvod, proč dotaz na API selhal. */
export function describeApiError(url: string, error: unknown, pageProtocol: string): string {
  const reason = error instanceof Error ? error.message : String(error);
  let host = '';
  try {
    host = new URL(url).hostname;
  } catch {
    /* neplatná adresa — stačí obecná hláška */
  }
  const local = host === 'localhost' || host === '127.0.0.1' || host === '[::1]';
  if (pageProtocol === 'https:' && url.startsWith('http://') && !local) {
    return `API na ${url} není dostupné (${reason}). Stránka běží přes HTTPS a prohlížeč z ní nepustí dotaz na nešifrovanou adresu jinou než localhost — spusťte viewer na tomto počítači, nebo si port přesměrujte (např. ssh -L 8080:localhost:8080 …).`;
  }
  return `API na ${url} není dostupné (${reason}). Běží viewer s přepínačem --api?`;
}
