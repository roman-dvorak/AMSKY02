import { useEffect, useMemo, useRef, useState } from 'react';
import { centerAverage, indexAtTime, skyColorRange } from '../lib/sky';
import type { ColorRange } from '../lib/sky';
import { formatUtc } from '../lib/time';
import type { SkyData } from '../lib/types';
import { SkyControls, SkyMap, useSkySettings } from './SkyMap';
import type { SkyPanel } from './SkyMap';

const CURSOR_EMIT_MS = 100;

interface Props {
  skies: SkyData[];
  onTimeChange(time: number): void;
}

function fmt(value: number): string {
  return Number.isFinite(value) ? `${value.toFixed(2)} °C` : '—';
}

/** Přehrávač zaznamenaných teplotních map se synchronizací kurzoru v grafech. */
export function SkyPlayer({ skies, onTimeChange }: Props) {
  // Časovou osu určuje senzor s nejvíce snímky; ostatní se dohledají podle času.
  const master = useMemo(() => skies.reduce((a, b) => (b.frames.length > a.frames.length ? b : a), skies[0]), [skies]);
  const maxIndex = Math.max(master.frames.length, 1) - 1;

  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [intervalMs, setIntervalMs] = useState(500);
  const autoRange = useMemo(() => skyColorRange(skies), [skies]);
  const [manualRange, setManualRange] = useState<ColorRange | null>(null);
  const range = manualRange ?? autoRange;
  const [settings, setSettings] = useSkySettings();

  useEffect(() => {
    setIndex(0);
    setPlaying(false);
    setManualRange(null);
  }, [skies]);

  const frameIndex = Math.min(index, maxIndex);
  const time = master.t[frameIndex];

  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => setIndex((i) => (i >= maxIndex ? 0 : i + 1)), intervalMs);
    return () => clearInterval(timer);
  }, [playing, intervalMs, maxIndex]);

  // Kurzor v grafech se posouvá nejvýš 10× za sekundu, jinak by přehrávání brzdil.
  const emitRef = useRef({ last: 0, timer: null as ReturnType<typeof setTimeout> | null, pending: 0 });
  const onTimeRef = useRef(onTimeChange);
  onTimeRef.current = onTimeChange;
  useEffect(() => {
    if (time === undefined) return;
    const state = emitRef.current;
    state.pending = time;
    const flush = () => {
      state.timer = null;
      state.last = Date.now();
      onTimeRef.current(state.pending);
    };
    const elapsed = Date.now() - state.last;
    if (elapsed >= CURSOR_EMIT_MS) flush();
    else if (!state.timer) state.timer = setTimeout(flush, CURSOR_EMIT_MS - elapsed);
  }, [time]);
  useEffect(() => {
    const state = emitRef.current;
    return () => {
      if (state.timer) clearTimeout(state.timer);
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLSelectElement || target instanceof HTMLTextAreaElement) {
        return;
      }
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        setIndex((i) => Math.max(Math.min(i, maxIndex) - 1, 0));
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        setIndex((i) => Math.min(i + 1, maxIndex));
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [maxIndex]);

  const panels: SkyPanel[] = useMemo(
    () =>
      skies.map((sky) => {
        const i = sky === master ? frameIndex : time === undefined ? -1 : indexAtTime(sky.t, time);
        const pixels = i >= 0 ? (sky.frames[i] ?? null) : null;
        if (!pixels) return { label: sky.name, rows: sky.rows, cols: sky.cols, pixels: null };
        const center = centerAverage(pixels, sky.rows, sky.cols);
        return {
          label: sky.name,
          rows: sky.rows,
          cols: sky.cols,
          pixels,
          caption: `centre ${fmt(center)} · centre − sensor ${fmt(center - sky.temp[i])}`,
        };
      }),
    [skies, master, frameIndex, time],
  );

  if (master.frames.length === 0) {
    return <div className="status-banner">The recording contains no sky thermal maps.</div>;
  }

  return (
    <div className="sky-viewer">
      <div className="sky-time">{formatUtc(time)}</div>
      <SkyMap panels={panels} range={range} settings={settings} />
      <div className="controls">
        <button type="button" onClick={() => setIndex(Math.max(frameIndex - 1, 0))} disabled={frameIndex === 0}>
          Previous
        </button>
        <button type="button" className="primary" onClick={() => setPlaying((p) => !p)}>
          {playing ? 'Pause' : 'Play'}
        </button>
        <button type="button" onClick={() => setIndex(Math.min(frameIndex + 1, maxIndex))} disabled={frameIndex >= maxIndex}>
          Next
        </button>
        <span className="hint">← →</span>
        <label className="slider-label">
          Frame {frameIndex + 1} / {maxIndex + 1}
          <input type="range" min={0} max={maxIndex} value={frameIndex} onChange={(e) => setIndex(Number(e.target.value))} />
        </label>
        <label className="slider-label speed-label">
          Speed {intervalMs} ms/frame
          <input type="range" min={50} max={2000} step={50} value={intervalMs} onChange={(e) => setIntervalMs(Number(e.target.value))} />
        </label>
      </div>
      <SkyControls
        settings={settings}
        onSettings={setSettings}
        range={range}
        auto={manualRange === null}
        autoLabel="whole recording"
        onRange={setManualRange}
        onAuto={() => setManualRange(null)}
      />
    </div>
  );
}
