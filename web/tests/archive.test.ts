import { describe, expect, it } from 'vitest';
import { filterFilesByDate, listAvailableDates, parseApacheDirectories, parseApacheFiles } from '../src/lib/archive';
import { fileBelongsToPeriod, nightDateKeyForFile, parseFileTimestamp, periodDescription } from '../src/lib/dayMode';

const INDEX = `<table>
<tr><th><a href="?C=N;O=D">Name</a></th><th><a href="?C=M;O=A">Last modified</a></th></tr>
<tr><td><a href="/meteo/">Parent Directory</a></td></tr>
<tr><td><a href="AMSKY01/">AMSKY01/</a></td></tr>
<tr><td><a href="AMSKY02/">AMSKY02/</a></td></tr>
<tr><td><a href="app/">app/</a></td></tr>
<tr><td><a href="AMSKY02_SVAKOV_20261110_23.h5">x</a></td></tr>
<tr><td><a href="AMSKY02_SVAKOV_20261111_00.h5">x</a></td></tr>
<tr><td><a href="AMSKY02_SVAKOV_20261111_13.h5">x</a></td></tr>
<tr><td><a href="notes.txt">x</a></td></tr>
</table>`;

describe('apache index', () => {
  it('lists subdirectories without parent and sort links', () => {
    expect(parseApacheDirectories(INDEX)).toEqual(['AMSKY01', 'AMSKY02', 'app']);
  });

  it('lists h5 files with absolute urls', () => {
    const files = parseApacheFiles(INDEX, 'https://x/meteo/svakov/AMSKY02/', '.h5');
    expect(files.map((f) => f.filename)).toEqual([
      'AMSKY02_SVAKOV_20261110_23.h5',
      'AMSKY02_SVAKOV_20261111_00.h5',
      'AMSKY02_SVAKOV_20261111_13.h5',
    ]);
    expect(files[0].url).toBe('https://x/meteo/svakov/AMSKY02/AMSKY02_SVAKOV_20261110_23.h5');
  });
});

describe('day / night periods', () => {
  const files = parseApacheFiles(INDEX, 'u/', '.h5');

  it('parses hourly file names', () => {
    expect(parseFileTimestamp('AMSKY02_SVAKOV_20261111_22.h5')).toEqual({ dateKey: '20261111', hour: 22 });
    expect(parseFileTimestamp('foo.h5')).toBeNull();
  });

  it('assigns a night to the date of its morning, across month ends', () => {
    expect(nightDateKeyForFile('20261130', 23)).toBe('20261201');
    expect(nightDateKeyForFile('20261201', 3)).toBe('20261201');
    expect(fileBelongsToPeriod('A_20261231_18.h5', '20270101', 'night')).toBe(true);
    expect(fileBelongsToPeriod('A_20270101_12.h5', '20270101', 'night')).toBe(false);
  });

  it('filters and lists periods', () => {
    expect(filterFilesByDate(files, '20261111', 'daytime')).toHaveLength(2);
    expect(filterFilesByDate(files, '20261111', 'night').map((f) => f.filename)).toEqual([
      'AMSKY02_SVAKOV_20261110_23.h5',
      'AMSKY02_SVAKOV_20261111_00.h5',
    ]);
    expect(listAvailableDates(files, 'daytime')).toEqual(['20261111', '20261110']);
    expect(listAvailableDates(files, 'night')).toEqual(['20261112', '20261111']);
    expect(periodDescription('night', '2026-11-11')).toBe('2026-11-10 12:00 – 2026-11-11 12:00 UTC');
  });
});

describe('archive sources', () => {
  it('normalizes typed addresses', async () => {
    const { normalizeSourceUrl, sourceLabel } = await import('../src/lib/sources');
    expect(normalizeSourceUrl(' space.astro.cz/meteo/svakov/AMSKY02 ')).toBe('https://space.astro.cz/meteo/svakov/AMSKY02/');
    expect(normalizeSourceUrl('http://host/a/b/?C=N;O=D#x')).toBe('http://host/a/b/');
    expect(normalizeSourceUrl('https://host/a/AMSKY02_X_20261111_22.h5')).toBe('https://host/a/');
    expect(normalizeSourceUrl('ftp://host/a/')).toBeNull();
    expect(normalizeSourceUrl('')).toBeNull();
    expect(sourceLabel('https://space.astro.cz/meteo/svakov/AMSKY02/')).toBe('svakov / AMSKY02');
  });

  it('keeps pinned sources first and recent ones by last use', async () => {
    const { sortSources } = await import('../src/lib/sources');
    const sorted = sortSources([
      { url: 'b', pinned: false, lastUsed: 1 },
      { url: 'z', pinned: true, lastUsed: 0 },
      { url: 'c', pinned: false, lastUsed: 5 },
      { url: 'a', pinned: true, lastUsed: 9 },
    ]);
    expect(sorted.map((s) => s.url)).toEqual(['a', 'z', 'c', 'b']);
  });
});
