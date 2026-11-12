/**
 * Zdroje archivu zadané uživatelem (URL adresářů s HDF5 logy).
 * Seznam naposledy použitých a připnutých zdrojů žije v localStorage prohlížeče.
 */
export interface ArchiveSource {
  url: string;
  pinned: boolean;
  lastUsed: number;
}

const STORAGE_KEY = 'amsky.archiveSources';
const MAX_RECENT = 8;

/** Doplní schéma a koncové lomítko; vrací `null`, když text není použitelná http(s) adresa. */
export function normalizeSourceUrl(input: string): string | null {
  let text = input.trim();
  if (!text) return null;
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) text = `https://${text}`;
  try {
    const url = new URL(text);
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
    url.hash = '';
    url.search = '';
    // Odkaz přímo na soubor se bere jako jeho adresář.
    if (/\.(h5|hdf5)$/i.test(url.pathname)) url.pathname = url.pathname.replace(/[^/]*$/, '');
    if (!url.pathname.endsWith('/')) url.pathname += '/';
    return url.toString();
  } catch {
    return null;
  }
}

/** Krátký název zdroje pro seznam: poslední dvě složky cesty. */
export function sourceLabel(url: string): string {
  try {
    const parsed = new URL(url);
    const parts = parsed.pathname.split('/').filter(Boolean).map(decodeURIComponent);
    return parts.length > 0 ? parts.slice(-2).join(' / ') : parsed.host;
  } catch {
    return url;
  }
}

/** Připnuté první (abecedně), pak ostatní od naposledy použitého. */
export function sortSources(list: ArchiveSource[]): ArchiveSource[] {
  return [...list].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    return a.pinned ? a.url.localeCompare(b.url) : b.lastUsed - a.lastUsed;
  });
}

export function loadSources(): ArchiveSource[] {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]');
    if (!Array.isArray(raw)) return [];
    return sortSources(
      raw
        .filter((item) => item && typeof item.url === 'string')
        .map((item) => ({ url: item.url, pinned: !!item.pinned, lastUsed: Number(item.lastUsed) || 0 })),
    );
  } catch {
    return [];
  }
}

function save(list: ArchiveSource[]): ArchiveSource[] {
  const sorted = sortSources(list);
  // Nepřipnutých se drží jen několik posledních.
  let recent = 0;
  const kept = sorted.filter((item) => item.pinned || ++recent <= MAX_RECENT);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(kept));
  } catch {
    /* soukromý režim nebo plné úložiště — seznam vydrží jen do zavření stránky */
  }
  return kept;
}

export function touchSource(list: ArchiveSource[], url: string, now = Date.now()): ArchiveSource[] {
  const existing = list.find((item) => item.url === url);
  const rest = list.filter((item) => item.url !== url);
  return save([...rest, { url, pinned: existing?.pinned ?? false, lastUsed: now }]);
}

export function setPinned(list: ArchiveSource[], url: string, pinned: boolean): ArchiveSource[] {
  return save(list.map((item) => (item.url === url ? { ...item, pinned } : item)));
}

export function removeSource(list: ArchiveSource[], url: string): ArchiveSource[] {
  return save(list.filter((item) => item.url !== url));
}
