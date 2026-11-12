import type { DayMode } from './dayMode';

/**
 * Stav v adrese: `view`, a pro archiv `src` (adresa zdroje), `date`, `mode`
 * a `files`, aby šel konkrétní pohled sdílet odkazem.
 */
export type View = 'live' | 'archive' | 'files';

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function params(): URLSearchParams {
  return new URLSearchParams(window.location.search);
}

export function readView(): View {
  const p = params();
  const view = p.get('view');
  if (view === 'live' || view === 'archive' || view === 'files') return view;
  // Odkaz bez `view`, ale s parametry archivu (i z původní aplikace).
  return p.has('src') || p.has('date') || p.has('files') ? 'archive' : 'live';
}

export function readDate(): string | null {
  const date = params().get('date');
  return date && DATE_PATTERN.test(date) ? date : null;
}

export function readDayMode(): DayMode {
  return params().get('mode') === 'night' ? 'night' : 'daytime';
}

export function readSource(): string | null {
  return params().get('src') || null;
}

export function readFiles(): string[] {
  return (params().get('files') ?? '')
    .split(',')
    .map((name) => name.trim())
    .filter(Boolean);
}

/** Nastaví (nebo při `null` smaže) parametry bez přidání záznamu do historie. */
export function writeParams(values: Record<string, string | null>): void {
  const url = new URL(window.location.href);
  for (const [key, value] of Object.entries(values)) {
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
  }
  if (url.toString() !== window.location.href) {
    window.history.replaceState(window.history.state, '', url.toString());
  }
}
