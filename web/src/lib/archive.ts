/**
 * Procházení archivu HDF5 logů vystaveného jako výpis adresáře webového
 * serveru (Apache/nginx autoindex). Adresu adresáře zadává uživatel; soubory
 * se jmenují `<zařízení>_YYYYMMDD_HH.h5`.
 */
import type { DayMode } from './dayMode';
import { dateKeyToInput, fileBelongsToPeriod, nightDateKeyForFile, parseFileTimestamp } from './dayMode';
import type { H5FileEntry } from './types';

function hrefs(html: string): string[] {
  return Array.from(html.matchAll(/href="([^"]+)"/gi), (m) => m[1]);
}

/** Relativní odkazy na podadresáře; řazení (`?C=N`) a rodič (`/…`, `../`) se vynechají. */
export function parseApacheDirectories(html: string): string[] {
  const out: string[] = [];
  for (const href of hrefs(html)) {
    if (!href.endsWith('/') || href.startsWith('/') || href.startsWith('?') || href.includes('://')) continue;
    const name = decodeURIComponent(href.slice(0, -1));
    if (!name || name.includes('/') || name === '.' || name === '..') continue;
    if (!out.includes(name)) out.push(name);
  }
  return out;
}

export function parseApacheFiles(html: string, baseUrl: string, extension: string): H5FileEntry[] {
  const out: H5FileEntry[] = [];
  const seen = new Set<string>();
  for (const href of hrefs(html)) {
    const clean = href.split('?')[0];
    if (!clean.toLowerCase().endsWith(extension)) continue;
    const filename = decodeURIComponent(clean.split('/').pop() ?? '');
    if (!filename || seen.has(filename)) continue;
    seen.add(filename);
    out.push({ filename, url: `${baseUrl}${encodeURIComponent(filename)}` });
  }
  return out;
}

async function fetchText(url: string, what: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch(url, { cache: 'no-store' });
  } catch {
    throw new Error(
      `Nelze načíst ${what}. Server není dostupný, nebo nepovoluje čtení z této stránky (chybí hlavička CORS).`,
    );
  }
  if (!response.ok) throw new Error(`Nelze načíst ${what} (${response.status})`);
  return response.text();
}

/**
 * Soubory .h5 ve zdrojovém adresáři. Když v něm žádné nejsou, zkusí se jeho
 * podadresáře — lze tak zadat i adresář stanice s více zařízeními.
 */
export async function listSourceFiles(sourceUrl: string): Promise<H5FileEntry[]> {
  const html = await fetchText(sourceUrl, 'výpis adresáře');
  const direct = parseApacheFiles(html, sourceUrl, '.h5');
  if (direct.length > 0) return direct.sort((a, b) => a.filename.localeCompare(b.filename));

  const subdirs = parseApacheDirectories(html);
  const lists = await Promise.all(
    subdirs.map(async (subdir) => {
      const url = `${sourceUrl}${encodeURIComponent(subdir)}/`;
      try {
        const listing = await fetchText(url, subdir);
        return parseApacheFiles(listing, url, '.h5').map((file) => ({ ...file, source: subdir }));
      } catch {
        return [];
      }
    }),
  );
  return lists.flat().sort((a, b) => a.filename.localeCompare(b.filename));
}

export async function fetchFile(entry: H5FileEntry): Promise<ArrayBuffer> {
  const response = await fetch(entry.url, { cache: 'no-store' });
  if (!response.ok) throw new Error(`Nelze načíst soubor ${entry.filename} (${response.status})`);
  return response.arrayBuffer();
}

/** Dostupná období (YYYYMMDD), nejnovější první. */
export function listAvailableDates(files: H5FileEntry[], mode: DayMode): string[] {
  const dates = new Set<string>();
  for (const file of files) {
    const parsed = parseFileTimestamp(file.filename);
    if (!parsed) continue;
    dates.add(mode === 'night' ? nightDateKeyForFile(parsed.dateKey, parsed.hour) : parsed.dateKey);
  }
  return Array.from(dates).sort((a, b) => b.localeCompare(a));
}

export function filterFilesByDate(files: H5FileEntry[], dateKey: string, mode: DayMode): H5FileEntry[] {
  return files.filter((file) => fileBelongsToPeriod(file.filename, dateKey, mode));
}

export function defaultDateInput(files: H5FileEntry[], mode: DayMode): string {
  const dates = listAvailableDates(files, mode);
  return dates.length === 0 ? new Date().toISOString().slice(0, 10) : dateKeyToInput(dates[0]);
}
