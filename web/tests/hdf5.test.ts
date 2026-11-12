import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { demoHello, demoTick } from '../src/lib/demo';
import { parseH5, writeH5 } from '../src/lib/hdf5';
import { lightSeries } from '../src/lib/light';
import { mergeDatasets } from '../src/lib/merge';
import { LiveSession } from '../src/lib/session';
import { skyColorRange } from '../src/lib/sky';
import { datasetTimeRange } from '../src/lib/types';

const sample = (name: string) => readFileSync(fileURLToPath(new URL(`../../doc/data/${name}`, import.meta.url)));

describe('HDF5 logs', () => {
  it('reads an AMSKY01 log from the Python logger', async () => {
    const data = await parseH5('AMSKY01_20260103_22.h5', sample('AMSKY01_20260103_22.h5'));
    expect(data.skies.map((s) => [s.name, s.rows, s.cols, s.frames.length])).toEqual([['sky', 12, 16, 1798]]);
    expect(data.lights.map((l) => [l.name, l.t.length])).toEqual([['light', 1798]]);
    expect(data.clouds).toEqual([]);
    expect(data.hygro.t).toHaveLength(1797);
    expect(data.hygro.temp[0]).toBeCloseTo(-2.31, 2);
    expect(data.lights[0].full[0]).toBe(2844);
    // 1767477600249414144 ns
    expect(data.lights[0].t[0]).toBe(1767477600249);
    expect(new Date(datasetTimeRange(data)!.from).toISOString().slice(0, 13)).toBe('2026-01-03T22');
    const range = skyColorRange(data.skies);
    expect(range.max).toBeGreaterThan(range.min);
    expect(lightSeries(data.lights[0]).fromDevice).toBe(false);
  });

  it('merges consecutive hourly files in time order', async () => {
    const a = await parseH5('a', sample('AMSKY01_20260103_23.h5'));
    const b = await parseH5('b', sample('AMSKY01_20260103_22.h5'));
    const merged = mergeDatasets([a, b]);
    const sky = merged.skies[0];
    expect(sky.frames).toHaveLength(a.skies[0].frames.length + b.skies[0].frames.length);
    expect(sky.t[0]).toBe(b.skies[0].t[0]);
    for (let i = 1; i < sky.t.length; i++) expect(sky.t[i]).toBeGreaterThanOrEqual(sky.t[i - 1]);
    expect(merged.hygro.t).toHaveLength(a.hygro.t.length + b.hygro.t.length);
  });

  it('round-trips a live recording through writeH5 / parseH5', async () => {
    const session = new LiveSession();
    demoHello().forEach((l) => session.ingestLine(l, 1_700_000_000_000));
    for (let step = 0; step < 4; step++) {
      demoTick(step, true).forEach((l) => session.ingestLine(l, 1_700_000_000_000 + step * 2000));
    }
    const bytes = await writeH5(session.data);
    const back = await parseH5('rec.h5', bytes);

    expect(back.skies.map((s) => [s.name, s.rows, s.cols, s.frames.length])).toEqual([
      ['sky1', 24, 32, 4],
      ['sky2', 24, 32, 4],
    ]);
    expect(back.skies[0].t).toEqual(session.data.skies[0].t);
    expect(Array.from(back.skies[1].frames[3])).toEqual(Array.from(session.data.skies[1].frames[3]));
    expect(back.clouds.map((c) => c.name)).toEqual(['cloud1', 'cloud2']);
    expect(back.clouds[0].center[2]).toBeCloseTo(session.data.clouds[0].center[2], 4);
    expect(back.lights.map((l) => l.name)).toEqual(['light0', 'light1']);
    expect(back.lights[1].sqm![0]).toBeCloseTo(session.data.lights[1].sqm![0], 4);
    expect(lightSeries(back.lights[0]).fromDevice).toBe(true);
    expect(back.hygro.t).toEqual(session.data.hygro.t);
  });

  it('rejects a file that is not HDF5', async () => {
    await expect(parseH5('bad.h5', new Uint8Array([1, 2, 3, 4]))).rejects.toThrow(/není platné HDF5/);
  });
});
