import { describe, expect, it } from 'vitest';
import { parseLine } from '../src/lib/protocol';
import { LineSplitter } from '../src/lib/serial';
import { LiveSession } from '../src/lib/session';
import { demoHello, demoTick } from '../src/lib/demo';

describe('parseLine', () => {
  it('parses AMSKY02 light with channel index', () => {
    expect(parseLine('$light,1,2100,3696,102,9876,600,20.91')).toEqual({
      type: 'light', channel: 1, lux: 0.0021, fullRaw: 3696, irRaw: 102, gain: 9876, integrationMs: 600, sqm: 20.91,
    });
  });

  it('parses AMSKY01 light without channel index and with unit suffixes', () => {
    const msg = parseLine('$light,12.34,1000,200,25x,100ms,21.50');
    expect(msg).toMatchObject({ type: 'light', channel: 0, lux: 12.34, gain: 25, integrationMs: 100, sqm: 21.5 });
  });

  it('parses cloud, cloud_meta, hygro and hello', () => {
    expect(parseLine('$cloud,2,-20.1,-20.2,-20.3,-20.4,-21.0\r\n')).toEqual({
      type: 'cloud', sensorId: 2, tl: -20.1, tr: -20.2, bl: -20.3, br: -20.4, center: -21,
    });
    expect(parseLine('$cloud_meta,1,3.300,9.760')).toEqual({ type: 'cloud_meta', sensorId: 1, vdd: 3.3, ta: 9.76 });
    expect(parseLine('$hygro,8.23,71.82,3.40')).toMatchObject({ temperature: 8.23, humidity: 71.82, dewPoint: 3.4, valid: true });
    expect(parseLine('$hygro,-999,-999,-999')).toMatchObject({ valid: false });
    expect(parseLine('$HELLO,AMSKY02B,E6614103E7452D2F,1.2.0,abc1234,main')).toMatchObject({
      type: 'hello', model: 'AMSKY02B', serial: 'E6614103E7452D2F', fwVersion: '1.2.0', gitBranch: 'main',
    });
  });

  it('parses 32x24 and 16x12 thermal maps and rejects truncated ones', () => {
    const full = parseLine(`$thrmap,2,${Array.from({ length: 768 }, (_, i) => (i / 10).toFixed(2)).join(',')}`);
    expect(full).toMatchObject({ type: 'thrmap', sensorId: 2, rows: 24, cols: 32 });
    if (full?.type === 'thrmap') expect(full.pixels[767]).toBeCloseTo(76.7);
    expect(parseLine(`$thrmap,1,${new Array(192).fill('1.5').join(',')}`)).toMatchObject({ rows: 12, cols: 16 });
    expect(parseLine(`$thrmap,1,${new Array(500).fill('1.5').join(',')}`)).toBeNull();
  });

  it('returns null for garbage and keeps comments', () => {
    expect(parseLine('')).toBeNull();
    expect(parseLine('$cloud,1,abc,1,2,3,4')).toBeNull();
    expect(parseLine('$cloud,1,1,2')).toBeNull();
    expect(parseLine('$unknown,1,2')).toBeNull();
    expect(parseLine('noise')).toBeNull();
    expect(parseLine('# thrmap streaming ON')).toEqual({ type: 'comment', text: 'thrmap streaming ON' });
  });
});

describe('LineSplitter', () => {
  it('reassembles lines split across chunks and handles CRLF', () => {
    const splitter = new LineSplitter();
    const enc = new TextEncoder();
    expect(splitter.push(enc.encode('$hygro,1,2'))).toEqual([]);
    expect(splitter.push(enc.encode(',3\r\n$cloud_meta,1,3.3,'))).toEqual(['$hygro,1,2,3']);
    expect(splitter.push(enc.encode('9.7\n'))).toEqual(['$cloud_meta,1,3.3,9.7']);
  });
});

describe('LiveSession', () => {
  it('builds a dataset from the simulated stream', () => {
    const session = new LiveSession();
    demoHello().forEach((l) => session.ingestLine(l, 1000));
    for (let step = 0; step < 3; step++) demoTick(step, true).forEach((l) => session.ingestLine(l, 2000 + step * 2000));
    session.ingestLine('$cloud,1,broken', 9000);

    expect(session.device?.model).toBe('AMSKY02B');
    expect(session.errorCount).toBe(1);
    expect(session.data.lights.map((l) => l.name)).toEqual(['light0', 'light1']);
    expect(session.data.clouds.map((c) => c.name)).toEqual(['cloud1', 'cloud2']);
    expect(session.data.skies.map((s) => [s.name, s.rows, s.cols, s.frames.length])).toEqual([
      ['sky1', 24, 32, 3],
      ['sky2', 24, 32, 3],
    ]);
    expect(session.data.hygro.t).toEqual([2000, 4000, 6000]);
    expect(session.data.clouds[0].vdd).toEqual([3.3, 3.3, 3.3]);
    expect(session.data.lights[0].sqm).toHaveLength(3);
    expect(session.latest.frames.get(2)?.pixels).toHaveLength(768);

    session.clear();
    expect(session.data.skies).toEqual([]);
    expect(session.device?.model).toBe('AMSKY02B');
  });
});
