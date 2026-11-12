import { describe, expect, it } from 'vitest';
import { describeApiError, normalizeApiUrl, SnapshotConverter } from '../src/lib/apiSource';
import { LiveSession } from '../src/lib/session';

const snapshot = () => ({
  timestamp: '2026-11-12T11:00:00',
  device: { device_model: 'AMSKY02B', serial_number: 'DF64909267660829', fw_version: '4b11e67' },
  hygro: { temp: 21.5, rh: 40.2, dew_point: 7.4 },
  light0: { lux: 0.0123, full: 300, ir: 100, gain: '25', itime: '600', sqm: 18.2, quality: 'OK' },
  light1: { lux: null, full: null, ir: null, gain: null, itime: null, sqm: null },
  mlx1: { vdd: 3.3, ta: 22.1 },
  mlx2: { vdd: null, ta: null },
  cloud1: { tl: 1, tr: 2, bl: 3, br: 4, center: 5 },
  cloud2: { tl: null, tr: null, bl: null, br: null, center: null },
  thrmap1: Array.from({ length: 768 }, (_, i) => i / 10),
  thrmap2: null,
});

describe('HTTP API source', () => {
  it('normalizes the API address', () => {
    expect(normalizeApiUrl('')).toBe('http://localhost:8080/data.json');
    expect(normalizeApiUrl('localhost:8080')).toBe('http://localhost:8080/data.json');
    expect(normalizeApiUrl('https://host/x/data.json')).toBe('https://host/x/data.json');
  });

  it('feeds a snapshot into the live session and skips unchanged sections', () => {
    const converter = new SnapshotConverter();
    const session = new LiveSession();
    const first = converter.toLines(snapshot());
    first.forEach((line) => session.ingestLine(line, 1000));

    expect(session.errorCount).toBe(0);
    expect(session.device?.serial).toBe('DF64909267660829');
    expect(session.latest.hygro?.humidity).toBe(40.2);
    expect(session.latest.light.get(0)).toMatchObject({ lux: 0.0123, fullRaw: 300, gain: 25, integrationMs: 600, sqm: 18.2 });
    expect(session.latest.light.has(1)).toBe(false);
    expect(session.data.clouds[0].vdd[0]).toBe(3.3);
    expect(session.data.skies[0]).toMatchObject({ name: 'sky1', rows: 24, cols: 32 });
    expect(session.data.skies[0].temp[0]).toBe(22.1);

    // Stejný snímek podruhé (jen s novým časem) nepřidá nic.
    expect(converter.toLines({ ...snapshot(), timestamp: 'later' })).toEqual([]);

    const next = snapshot();
    next.hygro.temp = 21.6;
    expect(converter.toLines(next)).toEqual(['$hygro,21.6,40.2,7.4']);
  });

  it('accepts a headless snapshot without SQM and the single-channel layout', () => {
    const lines = new SnapshotConverter().toLines({
      light: { lux: 0, full: 5, ir: 2, gain: '428x', itime: '600ms', sqm: null },
    });
    const session = new LiveSession();
    lines.forEach((line) => session.ingestLine(line, 1000));
    expect(session.errorCount).toBe(0);
    expect(session.latest.light.get(0)).toMatchObject({ gain: 428, integrationMs: 600 });
    expect(Number.isNaN(session.latest.light.get(0)!.sqm)).toBe(true);
  });

  it('explains the HTTPS restriction for non-local hosts', () => {
    expect(describeApiError('http://192.168.1.5:8080/data.json', new Error('Failed to fetch'), 'https:')).toMatch(/HTTPS/);
    expect(describeApiError('http://localhost:8080/data.json', new Error('Failed to fetch'), 'https:')).toMatch(/--api/);
  });
});
