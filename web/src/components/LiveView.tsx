import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { writeH5 } from '../lib/hdf5';
import { live } from '../lib/liveController';
import { serialSupported } from '../lib/serial';
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
        caption: `${formatClock(frame.time)} UTC · střed ${num(center)} °C`,
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
      setExportError(`Záznam se nepodařilo uložit: ${e instanceof Error ? e.message : String(e)}`);
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

  const lightChannels = Array.from(latest.light.keys()).sort((a, b) => a - b);
  const cloudIds = Array.from(latest.cloud.keys()).sort((a, b) => a - b);
  const hygro = latest.hygro?.valid ? latest.hygro : null;

  return (
    <>
      <section className="connect-bar">
        <div className="connect-actions">
          {connected || live.state === 'connecting' ? (
            <button type="button" className="primary" onClick={() => void live.disconnect()}>
              {live.source === 'demo' ? 'Zastavit simulátor' : 'Odpojit'}
            </button>
          ) : (
            <>
              <button type="button" className="primary" onClick={() => void live.connectSerial(baud)} disabled={!supported}>
                Připojit senzor…
              </button>
              <label className="inline-field">
                Rychlost
                <select value={baud} onChange={(e) => setBaud(Number(e.target.value))} disabled={!supported}>
                  {BAUD_RATES.map((rate) => (
                    <option key={rate} value={rate}>
                      {rate} Bd
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" onClick={() => live.startDemo()}>
                Simulátor
              </button>
            </>
          )}
        </div>

        <div className="connect-status">
          <span className={`dot ${connected ? (stale ? 'stale' : 'on') : live.state === 'connecting' ? 'stale' : ''}`} />
          <span>
            {live.state === 'connecting'
              ? 'Připojuji…'
              : !connected
                ? 'Nepřipojeno'
                : live.source === 'demo'
                  ? 'Simulátor (nejde o skutečná data)'
                  : stale
                    ? `Připojeno — ${Math.round((now - session.lastMessageAt!) / 1000)} s bez dat`
                    : 'Připojeno'}
          </span>
          {device && (
            <span className="device">
              {device.model} · SN {device.serial} · FW {device.fwVersion || '?'}
              {device.gitHash ? ` (${device.gitHash})` : ''}
            </span>
          )}
        </div>
      </section>

      {!supported && (
        <div className="status-banner">
          Tento prohlížeč neumí Web Serial, takže se k senzoru připojit nelze. Použijte Chrome, Edge nebo Operu na počítači
          (Firefox a Safari sériový port nepodporují). Prohlížení logů a simulátor fungují všude.
        </div>
      )}
      {live.error && <div className="error-banner">{live.error}</div>}
      {connected && session.messageCount === 0 && now - (session.log[0]?.time ?? now) > 5000 && (
        <div className="status-banner">
          Port je otevřený, ale nepřicházejí žádná data. Zkontrolujte, že je vybraný správný port a rychlost.
        </div>
      )}

      <section className={`tiles ${stale ? 'stale' : ''}`}>
        {(lightChannels.length > 0 ? lightChannels : [0]).map((ch) => {
          const l = latest.light.get(ch);
          return (
            <Tile
              key={`sqm${ch}`}
              label={lightChannels.length > 1 ? `Jas oblohy · light${ch}` : 'Jas oblohy'}
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
              label={cloudIds.length > 1 ? `Teplota oblohy · cloud${id}` : 'Teplota oblohy'}
              value={num(c?.center)}
              unit="°C"
              detail={delta !== undefined ? `${delta >= 0 ? '+' : '−'}${Math.abs(delta).toFixed(1)} °C vůči okolí` : undefined}
            />
          );
        })}
        <Tile label="Teplota vzduchu" value={num(hygro?.temperature)} unit="°C" />
        <Tile label="Vlhkost" value={num(hygro?.humidity, 1)} unit="%" detail={hygro ? `rosný bod ${num(hygro.dewPoint, 1)} °C` : undefined} />
      </section>

      <section className="sky-section">
        <div className="section-head">
          <h2>Obloha — teplotní mapa</h2>
          <label className="check">
            <input type="checkbox" checked={live.thrmap} onChange={(e) => void live.setThrmap(e.target.checked)} />
            Přijímat teplotní mapu
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
              autoLabel="podle aktuálního snímku"
              onRange={setManualRange}
              onAuto={() => setManualRange(null)}
            />
          </>
        ) : (
          <div className="status-banner">
            {connected
              ? live.thrmap
                ? 'Čekám na první snímek teplotní mapy…'
                : 'Příjem teplotní mapy je vypnutý.'
              : 'Po připojení se zde zobrazí teplotní mapa oblohy z obou senzorů.'}
          </div>
        )}
      </section>

      <section className="record-bar">
        <div>
          <strong>Záznam od připojení</strong>
          <span className="record-info">
            {range
              ? `${formatDuration(range.from, range.to)} · ${session.messageCount} zpráv · ${frameCount} snímků oblohy`
              : 'zatím prázdný'}
            {session.errorCount > 0 ? ` · ${session.errorCount} poškozených řádků` : ''}
          </span>
        </div>
        <div className="record-actions">
          <button type="button" onClick={() => void exportH5()} disabled={!range || exporting}>
            {exporting ? 'Ukládám…' : 'Stáhnout HDF5'}
          </button>
          <button type="button" onClick={() => onOpenRecording(snapshot(data, recordingName()))} disabled={!range}>
            Procházet záznam
          </button>
          <button type="button" onClick={() => session.clear()} disabled={!range}>
            Vymazat
          </button>
        </div>
      </section>
      {exportError && <div className="error-banner">{exportError}</div>}
      <p className="note">
        Záznam je jen v paměti této záložky — zavřením stránky zmizí, proto si ho stáhněte. Pro dlouhodobé logování použijte{' '}
        <code>amsky-viewer --headless --log</code>.
      </p>

      {range && <DatasetCharts data={data} resetKey={data} version={chartVersion} group="live" />}

      <section className="console">
        <div className="section-head">
          <h2>Konzole zařízení</h2>
          <div className="quick">
            {QUICK_COMMANDS.map((cmd) => (
              <button type="button" key={cmd} onClick={() => void live.send(cmd)} disabled={!connected}>
                {cmd}
              </button>
            ))}
          </div>
        </div>
        <div className="console-log" ref={logRef}>
          {logLength === 0 && <div className="console-empty">Zde se objeví komentáře zařízení a odeslané příkazy.</div>}
          {session.log.map((line) => (
            <div key={line.id} className={`console-line ${line.kind}`}>
              <span className="console-time">{formatClock(line.time)}</span>
              {line.text}
            </div>
          ))}
        </div>
        <form className="console-input" onSubmit={submitCommand}>
          <input
            type="text"
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            placeholder="např. set sqm_offset 8.5265"
            disabled={!connected}
            spellCheck={false}
            autoComplete="off"
          />
          <button type="submit" disabled={!connected || !command.trim()}>
            Odeslat
          </button>
        </form>
      </section>
    </>
  );
}
