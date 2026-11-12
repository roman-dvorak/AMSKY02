import type { FormEvent } from 'react';
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { DEFAULT_API_URL, normalizeApiUrl } from '../lib/apiSource';
import { writeH5 } from '../lib/hdf5';
import { live } from '../lib/liveController';
import { serialSupported } from '../lib/serial';
import { useStoredState } from '../lib/storage';
import type { ColorRange } from '../lib/sky';
import { centerAverage } from '../lib/sky';
import { formatClock, formatDuration, hourStamp } from '../lib/time';
import type { Dataset } from '../lib/types';
import { datasetTimeRange } from '../lib/types';
import { DatasetCharts } from './DatasetCharts';
import { SkyControls, SkyMap, useSkySettings } from './SkyMap';
import type { SkyPanel } from './SkyMap';

const BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400];
const QUICK_COMMANDS = ['config_show', 'config_save', 'thrmap_on', 'thrmap_off'];
/** Bez zprávy déle než tolik ms se hodnoty označí jako neaktuální. */
const STALE_MS = 10_000;

const isString = (value: unknown): value is string => typeof value === 'string';

type SourceChoice = 'serial' | 'api' | 'demo';
const isChoice = (value: unknown): value is SourceChoice => value === 'serial' || value === 'api' || value === 'demo';

/** Zdroje živých dat — vždy je aktivní jen jeden, proto se vybírají jako přepínač. */
const SOURCES: { id: SourceChoice; title: string; hint: string }[] = [
  { id: 'serial', title: 'USB sensor', hint: 'Directly over the serial port' },
  { id: 'api', title: 'Viewer API', hint: 'From a running amsky-viewer' },
  { id: 'demo', title: 'Simulator', hint: 'Made-up data to try the app' },
];

function num(value: number | undefined, digits = 2): string {
  return value !== undefined && Number.isFinite(value) ? value.toFixed(digits) : '—';
}

function Tile({ label, value, unit, detail }: { label: string; value: string; unit?: string; detail?: string }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className="tile-value">
        {value}
        {unit && value !== '—' && <span className="tile-unit"> {unit}</span>}
      </span>
      <span className="tile-detail">{detail ?? ' '}</span>
    </div>
  );
}

/** Kopie záznamu nezávislá na dalších přírůstcích živé relace. */
function snapshot(data: Dataset, label: string): Dataset {
  const copy = <T extends object>(obj: T): T =>
    Object.fromEntries(Object.entries(obj).map(([k, v]) => [k, Array.isArray(v) ? v.slice() : v])) as T;
  return {
    label,
    clouds: data.clouds.map(copy),
    lights: data.lights.map(copy),
    skies: data.skies.map(copy),
    hygro: copy(data.hygro),
  };
}

function download(bytes: Uint8Array, filename: string): void {
  const url = URL.createObjectURL(new Blob([bytes.slice().buffer], { type: 'application/x-hdf5' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export function LiveView({ onOpenRecording }: { onOpenRecording(data: Dataset): void }) {
  const session = live.session;
  const version = useSyncExternalStore(session.subscribe, session.getVersion);

  const [baud, setBaud] = useState(115200);
  const [apiUrl, setApiUrl] = useStoredState<string>('amsky.live.apiUrl', DEFAULT_API_URL, isString);
  const [apiUrlError, setApiUrlError] = useState<string | null>(null);
  const [choice, setChoice] = useStoredState<SourceChoice>('amsky.live.source', serialSupported() ? 'serial' : 'api', isChoice);
  const [command, setCommand] = useState('');
  const [manualRange, setManualRange] = useState<ColorRange | null>(null);
  const [skySettings, setSkySettings] = useSkySettings();
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  // Grafy se překreslují jen jednou za 2 s (perioda měření), ne s každou zprávou.
  const [chartVersion, setChartVersion] = useState(0);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    setChartVersion(session.version);
    const timer = setInterval(() => setChartVersion(session.version), 2000);
    return () => clearInterval(timer);
  }, [session]);

  const logLength = session.log.length;
  const lastLogId = session.log[logLength - 1]?.id;
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lastLogId]);

  const { latest, device, data } = session;
  const connected = live.state === 'connected';
  const supported = serialSupported();
  const canSend = connected && live.source !== 'api';
  const stale = connected && session.lastMessageAt !== null && now - session.lastMessageAt > STALE_MS;
  const range = datasetTimeRange(data);
  const frameCount = data.skies.reduce((sum, s) => sum + s.frames.length, 0);

  const panels: SkyPanel[] = useMemo(() => {
    const ids = Array.from(latest.frames.keys()).sort((a, b) => a - b);
    return ids.map((id) => {
      const frame = latest.frames.get(id)!;
      const center = centerAverage(frame.pixels, frame.rows, frame.cols);
      return {
        label: `sky${id}`,
        rows: frame.rows,
        cols: frame.cols,
        pixels: frame.pixels,
        caption: `${formatClock(frame.time)} UTC · centre ${num(center)} °C`,
      };
    });
    // `version` sleduje změny mapy `latest.frames`, která se mění na místě.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latest, version]);

  const autoRange: ColorRange = useMemo(() => {
    let min = Infinity;
    let max = -Infinity;
    for (const panel of panels) {
      if (!panel.pixels) continue;
      for (const v of panel.pixels) {
        if (v < min) min = v;
        if (v > max) max = v;
      }
    }
    if (!Number.isFinite(min) || !Number.isFinite(max)) return { min: 0, max: 1 };
    return min === max ? { min: min - 0.5, max: max + 0.5 } : { min, max };
  }, [panels]);

  const recordingName = () => `${device?.model || 'AMSKY'}_${hourStamp(range?.from ?? Date.now())}.h5`;

  const exportH5 = async () => {
    setExporting(true);
    setExportError(null);
    try {
      download(await writeH5(data), recordingName());
    } catch (e) {
      setExportError(`The recording could not be saved: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setExporting(false);
    }
  };

  const submitCommand = (event: React.FormEvent) => {
    event.preventDefault();
    if (!command.trim()) return;
    void live.send(command);
    setCommand('');
  };

  const connect = (event: FormEvent) => {
    event.preventDefault();
    setApiUrlError(null);
    if (choice === 'serial') {
      void live.connectSerial(baud);
    } else if (choice === 'demo') {
      live.startDemo();
    } else {
      let url: string;
      try {
        url = normalizeApiUrl(apiUrl);
      } catch {
        setApiUrlError(`Invalid API address: ${apiUrl}`);
        return;
      }
      setApiUrl(url);
      void live.connectApi(url);
    }
  };

  const sourceName = SOURCES.find((s) => s.id === live.source)?.title ?? '';
  const silentFor = session.lastMessageAt !== null ? Math.round((now - session.lastMessageAt) / 1000) : 0;

  const lightChannels = Array.from(latest.light.keys()).sort((a, b) => a - b);
  const cloudIds = Array.from(latest.cloud.keys()).sort((a, b) => a - b);
  const hygro = latest.hygro?.valid ? latest.hygro : null;

  return (
    <>
      {connected || live.state === 'connecting' ? (
        <section className="card connection">
          <div className="connection-state">
            <span className={`dot ${connected && !stale ? 'on' : 'stale'}`} />
            <div className="connection-text">
              <strong>
                {live.state === 'connecting' ? 'Connecting…' : stale ? `No data for ${silentFor} s` : 'Connected'}
                {sourceName && <span className="connection-source"> · {sourceName}</span>}
              </strong>
              <span className="device">
                {live.source === 'demo'
                  ? 'Simulated values — not real measurements'
                  : live.source === 'api'
                    ? live.apiUrl
                    : !device
                      ? 'Waiting for the device to identify itself…'
                      : null}
                {device && live.source === 'api' && ' · '}
                {device &&
                  live.source !== 'demo' &&
                  `${device.model} · SN ${device.serial} · FW ${device.fwVersion || '?'}${device.gitHash ? ` (${device.gitHash})` : ''}`}
              </span>
            </div>
          </div>
          <button type="button" onClick={() => void live.disconnect()}>
            {live.source === 'demo' ? 'Stop simulator' : 'Disconnect'}
          </button>
        </section>
      ) : (
        <section className="card source-card">
          <div className="card-head">
            <h2>Choose a data source</h2>
            <span className="connection-idle">
              <span className="dot" /> Not connected
            </span>
          </div>
          <div className="choices" role="radiogroup" aria-label="Live data source">
            {SOURCES.map((source) => (
              <label key={source.id} className={`choice ${choice === source.id ? 'selected' : ''}`}>
                <input
                  type="radio"
                  name="live-source"
                  value={source.id}
                  checked={choice === source.id}
                  onChange={() => {
                    setChoice(source.id);
                    setApiUrlError(null);
                  }}
                />
                <span className="choice-mark" aria-hidden="true" />
                <span className="choice-text">
                  <span className="choice-title">{source.title}</span>
                  <span className="choice-hint">{source.hint}</span>
                </span>
              </label>
            ))}
          </div>
          <form className="source-setup" onSubmit={connect}>
            {choice === 'serial' && (
              <>
                <p className="source-desc">
                  Plug the sensor into this computer. The browser will ask which serial port to use.
                  {!supported && (
                    <span className="source-warning">
                      {' '}
                      This browser has no Web Serial support — use Chrome, Edge or Opera on a desktop computer (Firefox and
                      Safari cannot open serial ports).
                    </span>
                  )}
                </p>
                <label className="inline-field">
                  Baud rate
                  <select value={baud} onChange={(e) => setBaud(Number(e.target.value))} disabled={!supported}>
                    {BAUD_RATES.map((rate) => (
                      <option key={rate} value={rate}>
                        {rate}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            {choice === 'api' && (
              <>
                <p className="source-desc">
                  Read-only view of a sensor that <code>amsky-viewer --api</code> is already logging. The serial port stays
                  with the viewer.
                </p>
                <label className="inline-field grow">
                  Address
                  <input
                    type="text"
                    value={apiUrl}
                    onChange={(e) => setApiUrl(e.target.value)}
                    placeholder={DEFAULT_API_URL}
                    spellCheck={false}
                  />
                </label>
              </>
            )}
            {choice === 'demo' && (
              <p className="source-desc">No hardware needed. The simulator produces plausible but made-up measurements.</p>
            )}
            <button type="submit" className="primary" disabled={choice === 'serial' && !supported}>
              {choice === 'demo' ? 'Start simulator' : choice === 'serial' ? 'Connect…' : 'Connect'}
            </button>
          </form>
        </section>
      )}

      {(apiUrlError ?? live.error) && <div className="error-banner">{apiUrlError ?? live.error}</div>}
      {connected && live.source === 'serial' && session.messageCount === 0 && now - (session.log[0]?.time ?? now) > 5000 && (
        <div className="status-banner">
          The port is open but no data is arriving. Check that the right port and baud rate are selected.
        </div>
      )}

      <section className={`tiles ${stale ? 'stale' : ''}`}>
        {(lightChannels.length > 0 ? lightChannels : [0]).map((ch) => {
          const l = latest.light.get(ch);
          return (
            <Tile
              key={`sqm${ch}`}
              label={lightChannels.length > 1 ? `Sky brightness · light${ch}` : 'Sky brightness'}
              value={l && l.sqm > 0 ? num(l.sqm) : '—'}
              unit="mag/arcsec²"
              detail={l ? `${l.lux.toPrecision(3)} lx · gain ${l.gain}× · ${l.integrationMs} ms` : undefined}
            />
          );
        })}
        {(cloudIds.length > 0 ? cloudIds : [1]).map((id) => {
          const c = latest.cloud.get(id);
          const delta = c && hygro ? c.center - hygro.temperature : undefined;
          return (
            <Tile
              key={`cloud${id}`}
              label={cloudIds.length > 1 ? `Sky temperature · cloud${id}` : 'Sky temperature'}
              value={num(c?.center)}
              unit="°C"
              detail={delta !== undefined ? `${delta >= 0 ? '+' : '−'}${Math.abs(delta).toFixed(1)} °C vs. ambient` : undefined}
            />
          );
        })}
        <Tile label="Air temperature" value={num(hygro?.temperature)} unit="°C" />
        <Tile label="Humidity" value={num(hygro?.humidity, 1)} unit="%" detail={hygro ? `dew point ${num(hygro.dewPoint, 1)} °C` : undefined} />
      </section>

      <div className="live-grid">
        <section className="card sky-section">
          <div className="card-head">
            <h2>Sky thermal map</h2>
            <label className="check">
              <input
                type="checkbox"
                checked={live.thrmap}
                disabled={live.source === 'api'}
                onChange={(e) => void live.setThrmap(e.target.checked)}
              />
              Receive thermal map
            </label>
          </div>
          {panels.length > 0 ? (
            <>
              <SkyMap panels={panels} range={manualRange ?? autoRange} settings={skySettings} />
              <SkyControls
                settings={skySettings}
                onSettings={setSkySettings}
                range={manualRange ?? autoRange}
                auto={manualRange === null}
                autoLabel="current frame"
                onRange={setManualRange}
                onAuto={() => setManualRange(null)}
              />
            </>
          ) : (
            <div className="empty">
              {connected
                ? live.thrmap
                  ? 'Waiting for the first thermal map frame…'
                  : 'Thermal map reception is turned off.'
                : 'The sky thermal map from both sensors appears here once connected.'}
            </div>
          )}
        </section>

        <div className="live-side">
          <section className="card recording">
            <div className="card-head">
              <h2>Session recording</h2>
              <span className="record-info">
                {range ? formatDuration(range.from, range.to) : 'empty'}
              </span>
            </div>
            <p className="record-stats">
              {range
                ? `${session.messageCount} messages · ${frameCount} sky frames`
                : 'Everything received since connecting is kept here.'}
              {session.errorCount > 0 ? ` · ${session.errorCount} corrupted lines` : ''}
            </p>
            <div className="record-actions">
              <button type="button" onClick={() => void exportH5()} disabled={!range || exporting}>
                {exporting ? 'Saving…' : 'Download HDF5'}
              </button>
              <button type="button" onClick={() => onOpenRecording(snapshot(data, recordingName()))} disabled={!range}>
                Browse recording
              </button>
              <button type="button" className="quiet" onClick={() => session.clear()} disabled={!range}>
                Clear
              </button>
            </div>
            {exportError && <div className="error-banner">{exportError}</div>}
            <p className="note">
              Kept only in this tab's memory — download it before closing the page. For long-term logging use{' '}
              <code>amsky-viewer --headless --log</code>.
            </p>
          </section>

          <section className="card console">
            <div className="card-head">
              <h2>Device console</h2>
            </div>
            <div className="console-log" ref={logRef}>
              {logLength === 0 && <div className="console-empty">Device comments and sent commands appear here.</div>}
              {session.log.map((line) => (
                <div key={line.id} className={`console-line ${line.kind}`}>
                  <span className="console-time">{formatClock(line.time)}</span>
                  {line.text}
                </div>
              ))}
            </div>
            <div className="quick">
              {QUICK_COMMANDS.map((cmd) => (
                <button type="button" key={cmd} onClick={() => void live.send(cmd)} disabled={!canSend}>
                  {cmd}
                </button>
              ))}
            </div>
            <form className="console-input" onSubmit={submitCommand}>
              <input
                type="text"
                value={command}
                onChange={(e) => setCommand(e.target.value)}
                placeholder={live.source === 'api' ? 'The API is read-only' : 'e.g. set sqm_offset 8.5265'}
                aria-label="Command for the device"
                disabled={!canSend}
                spellCheck={false}
                autoComplete="off"
              />
              <button type="submit" disabled={!canSend || !command.trim()}>
                Send
              </button>
            </form>
          </section>
        </div>
      </div>

      {range && <DatasetCharts data={data} resetKey={data} version={chartVersion} group="live" />}
    </>
  );
}
