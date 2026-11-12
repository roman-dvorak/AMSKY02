import { useMemo } from 'react';
import { lightSeries } from '../lib/light';
import type { Dataset } from '../lib/types';
import type { SeriesConfig } from './TimeSeriesChart';
import { TimeSeriesChart } from './TimeSeriesChart';

interface Props {
  data: Dataset;
  cursorTime?: number | null;
  /** Mění se, když jde o jiná data (jiný soubor, vymazaný záznam) — zruší zoom. */
  resetKey: unknown;
  /** Roste při přidání vzorků do týchž dat (živý záznam). */
  version?: number;
  /** Skupina pro společné přiblížení grafů; různé pohledy mají různou. */
  group: string;
}

const CLOUD_COLORS = ['#7ee787', '#79c0ff', '#d2a8ff', '#f2cc60'];
/** Barvy [vše, IR] pro jednotlivé kanály světelného čidla. */
const LIGHT_COLORS = [
  ['#f2cc60', '#ff7b72'],
  ['#56d4dd', '#d2a8ff'],
];

/** Čtveřice grafů společná pro živý záznam i HDF5 logy. */
export function DatasetCharts({ data, cursorTime = null, resetKey, version = 0, group }: Props) {
  const charts = useMemo(() => {
    const cloud: SeriesConfig[] = data.clouds.map((c, i) => ({
      name: `${c.name} centre`,
      t: c.t,
      v: c.center,
      color: CLOUD_COLORS[i % CLOUD_COLORS.length],
      lineWidth: 2,
      lineType: i % 2 === 1 ? 'dashed' : 'solid',
    }));

    const hygro: SeriesConfig[] = [
      { name: 'temperature', t: data.hygro.t, v: data.hygro.temp, color: '#79c0ff' },
      { name: 'humidity', t: data.hygro.t, v: data.hygro.hum, color: '#f2cc60', yAxisIndex: 1 },
    ];

    const lux: SeriesConfig[] = [];
    const sqm: SeriesConfig[] = [];
    let fromDevice = false;
    data.lights.forEach((light, i) => {
      const [colorAll, colorIr] = LIGHT_COLORS[i % LIGHT_COLORS.length];
      const derived = lightSeries(light);
      fromDevice ||= derived.fromDevice;
      const label = data.lights.length > 1 ? `${light.name} ` : '';
      lux.push({ name: `${label}lux`, t: light.t, v: derived.luxAll, color: colorAll, lineWidth: 2 });
      if (derived.luxIr) lux.push({ name: `${label}IR lux`, t: light.t, v: derived.luxIr, color: colorIr, lineWidth: 2 });
      lux.push({ name: `${label}full raw`, t: light.t, v: light.full, color: colorAll, yAxisIndex: 1, lineWidth: 1, lineType: 'dotted' });
      lux.push({ name: `${label}IR raw`, t: light.t, v: light.ir, color: colorIr, yAxisIndex: 1, lineWidth: 1, lineType: 'dotted' });
      sqm.push({ name: `${label}SQM`, t: light.t, v: derived.sqmAll, color: colorAll, lineWidth: 2 });
      if (derived.sqmIr) sqm.push({ name: `${label}IR SQM`, t: light.t, v: derived.sqmIr, color: colorIr, lineWidth: 2 });
    });

    return { cloud, hygro, lux, sqm, fromDevice };
    // `version` sleduje přírůstky do polí, která se mění na místě.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, version]);

  return (
    <section className="charts-grid">
      <TimeSeriesChart
        className="wide-chart"
        title="Sky temperature — centre of the field of view (UTC)"
        yLeft="°C"
        series={charts.cloud}
        cursorTime={cursorTime}
        resetKey={resetKey}
        group={group}
      />
      <TimeSeriesChart
        title="Air temperature and humidity"
        yLeft="°C"
        yRight="%"
        series={charts.hygro}
        cursorTime={cursorTime}
        resetKey={resetKey}
        group={group}
      />
      <TimeSeriesChart
        title={charts.fromDevice ? 'Illuminance (device value)' : 'Illuminance (computed from raw counts)'}
        yLeft="lux"
        yRight="raw"
        series={charts.lux}
        cursorTime={cursorTime}
        resetKey={resetKey}
        group={group}
      />
      <TimeSeriesChart
        className="wide-chart"
        title={charts.fromDevice ? 'Sky brightness (device value)' : 'Sky brightness (computed from raw counts)'}
        yLeft="mag/arcsec²"
        series={charts.sqm}
        cursorTime={cursorTime}
        resetKey={resetKey}
        group={group}
      />
    </section>
  );
}
