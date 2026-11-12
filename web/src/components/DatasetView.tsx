import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { formatDuration, formatUtc } from '../lib/time';
import type { Dataset } from '../lib/types';
import { datasetTimeRange } from '../lib/types';
import { DatasetCharts } from './DatasetCharts';
import { SkyPlayer } from './SkyPlayer';

interface Props {
  data: Dataset;
  /** Položky informačního pruhu před časovým rozsahem (stanice, režim…). */
  info?: { label: string; value: ReactNode }[];
  /** Skupina grafů pro společné přiblížení. */
  group: string;
}

/** Zobrazení jednoho načteného záznamu: souhrn, grafy a přehrávač oblohy. */
export function DatasetView({ data, info = [], group }: Props) {
  const [cursor, setCursor] = useState<number | null>(null);
  useEffect(() => setCursor(null), [data]);

  const range = datasetTimeRange(data);
  if (!range) return <div className="status-banner">Soubor neobsahuje žádná data.</div>;

  const items = [
    ...info,
    ...(data.device
      ? [
          {
            label: 'Zařízení',
            value: `${data.device.model || 'AMSKY'} · SN ${data.device.serial}${data.device.fwVersion ? ` · FW ${data.device.fwVersion}` : ''}`,
          },
        ]
      : []),
    { label: 'Od', value: formatUtc(range.from) },
    { label: 'Do', value: formatUtc(range.to) },
    { label: 'Délka', value: formatDuration(range.from, range.to) },
  ];

  return (
    <>
      <section className="info-banner">
        {items.map((item) => (
          <div className="info-item" key={item.label}>
            <span className="info-label">{item.label}</span>
            <span className="info-value">{item.value}</span>
          </div>
        ))}
        {cursor !== null && (
          <div className="info-item">
            <span className="info-label">Pozice</span>
            <span className="info-value cursor-highlight">{formatUtc(cursor)}</span>
          </div>
        )}
      </section>

      <DatasetCharts data={data} cursorTime={cursor} resetKey={data} group={group} />

      <section className="sky-section">
        <h2>Obloha — {data.skies.map((s) => s.name).join(' a ') || 'teplotní mapa'}</h2>
        {data.skies.length > 0 ? (
          <SkyPlayer skies={data.skies} onTimeChange={setCursor} />
        ) : (
          <div className="status-banner">Záznam neobsahuje teplotní mapy oblohy.</div>
        )}
      </section>
    </>
  );
}
