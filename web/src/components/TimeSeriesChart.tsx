import { LineChart } from 'echarts/charts';
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  ToolboxComponent,
  TooltipComponent,
} from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { useEffect, useMemo, useRef, useState } from 'react';
import { movingAverage } from '../lib/smooth';
import { useStoredState } from '../lib/storage';

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DataZoomComponent,
  MarkLineComponent,
  ToolboxComponent,
  CanvasRenderer,
]);

export interface SeriesConfig {
  name: string;
  t: number[];
  v: number[];
  color: string;
  yAxisIndex?: number;
  lineWidth?: number;
  lineType?: 'solid' | 'dashed' | 'dotted';
}

interface Props {
  title: string;
  series: SeriesConfig[];
  yLeft?: string;
  yRight?: string | null;
  /** Čas (ms) svislého kurzoru synchronizovaného s přehrávačem oblohy. */
  cursorTime?: number | null;
  height?: number;
  /** Změna hodnoty znamená jiná data: graf se postaví znovu a zruší se zoom. */
  resetKey?: unknown;
  className?: string;
  /** Grafy se stejnou skupinou mají společné přiblížení a kurzor myši. */
  group?: string;
}

/** Uživatelské nastavení jednoho grafu (ukládá se podle jeho názvu). */
interface ChartOptions {
  yMin: number | null;
  yMax: number | null;
  log: boolean;
  invert: boolean;
  /** Šířka klouzavého průměru ve vzorcích; 0 = bez vyhlazení. */
  smooth: number;
  points: boolean;
}

const DEFAULT_OPTIONS: ChartOptions = { yMin: null, yMax: null, log: false, invert: false, smooth: 0, points: false };
const SMOOTH_CHOICES = [0, 5, 15, 60];

function isOptions(value: unknown): value is ChartOptions {
  const v = value as ChartOptions | null;
  return !!v && typeof v.log === 'boolean' && typeof v.invert === 'boolean' && typeof v.smooth === 'number';
}

function cursorLine(cursor: number | null | undefined) {
  if (cursor == null) return { data: [] };
  return {
    silent: true,
    symbol: 'none',
    animation: false,
    lineStyle: { color: '#f0b849', width: 2, type: 'solid' },
    label: { show: false },
    data: [{ xAxis: cursor }],
  };
}

function pairs(series: SeriesConfig, options: ChartOptions): [number, number | null][] {
  const n = Math.min(series.t.length, series.v.length);
  const left = (series.yAxisIndex ?? 0) === 0;
  const values = options.smooth > 1 ? movingAverage(series.v, options.smooth) : series.v;
  const out = new Array<[number, number | null]>(n);
  for (let i = 0; i < n; i++) {
    const v = values[i];
    // Logaritmická osa neumí nulu ani záporné hodnoty — vykreslí se jako mezera.
    out[i] = [series.t[i], !Number.isFinite(v) || (left && options.log && v <= 0) ? null : v];
  }
  return out;
}

function OptionalNumber({ label, value, onChange }: { label: string; value: number | null; onChange(v: number | null): void }) {
  const [text, setText] = useState<string | null>(null);
  return (
    <label>
      {label}
      <input
        type="number"
        placeholder="auto"
        value={text ?? (value === null ? '' : String(value))}
        onChange={(e) => {
          setText(e.target.value);
          const parsed = Number(e.target.value);
          if (e.target.value.trim() === '') onChange(null);
          else if (Number.isFinite(parsed)) onChange(parsed);
        }}
        onBlur={() => setText(null)}
      />
    </label>
  );
}

export function TimeSeriesChart({
  title,
  series,
  yLeft = '°C',
  yRight = null,
  cursorTime = null,
  height = 280,
  resetKey,
  className,
  group,
}: Props) {
  const [options, setOptions] = useStoredState<ChartOptions>(`amsky.chart.${title.split(' (')[0]}`, DEFAULT_OPTIONS, isOptions);
  const [showOptions, setShowOptions] = useState(false);
  const customized = useMemo(() => JSON.stringify(options) !== JSON.stringify(DEFAULT_OPTIONS), [options]);
  // Neplatná kombinace (min ≥ max, záporné minimum v log. měřítku) se osy nedotkne.
  const rangeValid = options.yMin === null || options.yMax === null || options.yMax > options.yMin;
  const yMin = rangeValid && !(options.log && options.yMin !== null && options.yMin <= 0) ? options.yMin : null;
  const yMax = rangeValid ? options.yMax : null;
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const builtKey = useRef<unknown>(Symbol('unbuilt'));
  const cursorRef = useRef(cursorTime);
  cursorRef.current = cursorTime;

  useEffect(() => {
    const chart = echarts.init(hostRef.current!);
    chartRef.current = chart;
    // Nová instance grafu nemá žádné nastavení — další vykreslení ji postaví celou.
    builtKey.current = Symbol('unbuilt');
    if (group) {
      chart.group = group;
      echarts.connect(group);
    }
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(hostRef.current!);
    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, [group]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const hasRight = series.some((s) => s.yAxisIndex === 1) || !!yRight;
    let min = Infinity;
    let max = -Infinity;
    for (const s of series) {
      if (s.t.length === 0) continue;
      min = Math.min(min, s.t[0]);
      max = Math.max(max, s.t[s.t.length - 1]);
    }
    const padding = Math.max((max - min) * 0.02, 30_000);
    const rebuild = builtKey.current !== resetKey;
    builtKey.current = resetKey;

    chart.setOption(
      {
        backgroundColor: 'transparent',
        animation: false,
        // Všechny časy v aplikaci jsou UTC (stejně jako názvy hodinových souborů).
        useUTC: true,
        title: { text: title, left: 0, top: 0, textStyle: { color: '#dfe7f3', fontSize: 14, fontWeight: 600 } },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
          backgroundColor: 'rgba(15, 22, 38, 0.95)',
          borderColor: '#2c3a55',
          textStyle: { color: '#e6ecf5', fontSize: 12 },
          valueFormatter: (value: unknown) => (typeof value === 'number' ? value.toFixed(2) : '—'),
        },
        toolbox: {
          right: 0,
          top: -4,
          itemSize: 14,
          iconStyle: { borderColor: '#8593ab' },
          emphasis: { iconStyle: { borderColor: '#e8f0fa' } },
          feature: {
            dataZoom: { yAxisIndex: 'none', title: { zoom: 'Zoom to selection', back: 'Undo zoom' } },
            restore: { title: 'Reset' },
            saveAsImage: { title: 'Save as PNG', backgroundColor: '#0f1626', name: title },
          },
        },
        legend: { top: 26, left: 0, right: 0, type: 'scroll', icon: 'rect', itemWidth: 14, itemHeight: 3, textStyle: { color: '#a9b6cc' } },
        grid: { left: 52, right: hasRight ? 52 : 16, top: 78, bottom: 56 },
        // Při průběžné aktualizaci se dataZoom neposílá, aby zůstalo přiblížení uživatele.
        ...(rebuild
          ? {
              dataZoom: [
                { type: 'inside', xAxisIndex: 0, start: 0, end: 100 },
                {
                  type: 'slider',
                  xAxisIndex: 0,
                  height: 18,
                  bottom: 10,
                  start: 0,
                  end: 100,
                  borderColor: '#1f2a40',
                  backgroundColor: 'transparent',
                  fillerColor: 'rgba(79, 127, 232, 0.16)',
                  dataBackground: { lineStyle: { color: '#3b4c6e' }, areaStyle: { color: '#1c2944' } },
                  selectedDataBackground: { lineStyle: { color: '#6491f2' }, areaStyle: { color: '#2a3f6b' } },
                  handleStyle: { color: '#162036', borderColor: '#51607c' },
                  moveHandleStyle: { color: '#2c3a55' },
                  emphasis: { handleStyle: { borderColor: '#6491f2' }, moveHandleStyle: { color: '#3b4c6e' } },
                  textStyle: { color: '#8593ab' },
                  brushSelect: false,
                },
              ],
            }
          : {}),
        xAxis: {
          type: 'time',
          min: Number.isFinite(min) ? min - padding : undefined,
          max: Number.isFinite(max) ? max + padding : undefined,
          axisLabel: { color: '#8593ab' },
          axisLine: { lineStyle: { color: '#2c3a55' } },
        },
        yAxis: [
          {
            type: options.log ? 'log' : 'value',
            name: yLeft,
            nameLocation: 'end',
            scale: true,
            inverse: options.invert,
            min: yMin ?? undefined,
            max: yMax ?? undefined,
            nameTextStyle: { color: '#8593ab' },
            axisLabel: { color: '#8593ab' },
            splitLine: { lineStyle: { color: '#1a2438' } },
          },
          ...(hasRight
            ? [
                {
                  type: 'value',
                  name: yRight ?? '',
                  position: 'right',
                  scale: true,
                  nameTextStyle: { color: '#8593ab' },
                  axisLabel: { color: '#8593ab' },
                  splitLine: { show: false },
                },
              ]
            : []),
        ],
        series: series.map((s, index) => ({
          id: s.name,
          name: s.name,
          type: 'line',
          showSymbol: options.points,
          symbolSize: 4,
          connectNulls: false,
          sampling: options.points ? undefined : 'lttb',
          yAxisIndex: s.yAxisIndex ?? 0,
          lineStyle: { width: s.lineWidth ?? 1.5, color: s.color, type: s.lineType ?? 'solid' },
          itemStyle: { color: s.color },
          data: pairs(s, options),
          ...(index === 0 ? { markLine: cursorLine(cursorRef.current) } : {}),
        })),
      },
      rebuild ? { notMerge: true } : { replaceMerge: ['series', 'yAxis'] },
    );
  }, [series, title, yLeft, yRight, resetKey, options, yMin, yMax]);

  useEffect(() => {
    const chart = chartRef.current;
    const first = series[0];
    if (!chart || !first) return;
    chart.setOption({ series: [{ id: first.name, markLine: cursorLine(cursorTime) }] });
    // `series` záměrně chybí: kurzor se mění mnohem častěji než data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cursorTime]);

  const set = (patch: Partial<ChartOptions>) => setOptions({ ...options, ...patch });

  // ECharts měří vlastní prvek včetně paddingu, proto má okraj až obal.
  return (
    <div className={`chart-card ${className ?? ''}`}>
      <div ref={hostRef} className="chart" style={{ height }} />
      <div className="chart-options-bar">
        <button
          type="button"
          className={`chart-options-toggle ${customized ? 'active' : ''}`}
          aria-expanded={showOptions}
          onClick={() => setShowOptions((v) => !v)}
        >
          {showOptions ? 'Hide options' : customized ? 'Chart options •' : 'Chart options'}
        </button>
        {showOptions && (
          <div className="chart-options">
            <OptionalNumber label={`${yLeft} axis from`} value={options.yMin} onChange={(v) => set({ yMin: v })} />
            <OptionalNumber label="to" value={options.yMax} onChange={(v) => set({ yMax: v })} />
            <label className="check">
              <input type="checkbox" checked={options.log} onChange={(e) => set({ log: e.target.checked })} />
              Logarithmic
            </label>
            <label className="check">
              <input type="checkbox" checked={options.invert} onChange={(e) => set({ invert: e.target.checked })} />
              Inverted
            </label>
            <label>
              Smoothing
              <select value={options.smooth} onChange={(e) => set({ smooth: Number(e.target.value) })}>
                {SMOOTH_CHOICES.map((n) => (
                  <option key={n} value={n}>
                    {n === 0 ? 'off' : `${n} samples`}
                  </option>
                ))}
              </select>
            </label>
            <label className="check">
              <input type="checkbox" checked={options.points} onChange={(e) => set({ points: e.target.checked })} />
              Points
            </label>
            <button type="button" onClick={() => setOptions(DEFAULT_OPTIONS)} disabled={!customized}>
              Defaults
            </button>
            {!rangeValid && <span className="chart-options-error">The upper limit must be greater than the lower one.</span>}
            {options.log && options.yMin !== null && options.yMin <= 0 && (
              <span className="chart-options-error">On a logarithmic scale the lower limit must be positive.</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
