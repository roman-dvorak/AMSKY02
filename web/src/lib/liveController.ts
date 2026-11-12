/**
 * Řídí zdroj živých dat (sériový port, HTTP API vieweru nebo simulátor) a plní jím relaci.
 * Žije mimo React, takže spojení přežije přepnutí záložky v aplikaci.
 */
import { describeApiError, SnapshotConverter } from './apiSource';
import { demoHello, demoTick } from './demo';
import type { LinkState } from './serial';
import { SerialLink } from './serial';
import { LiveSession } from './session';

export type Source = 'serial' | 'api' | 'demo' | null;

const API_POLL_MS = 1000;
const API_TIMEOUT_MS = 4000;

export class LiveController {
  readonly session = new LiveSession();
  state: LinkState = 'disconnected';
  source: Source = null;
  error: string | null = null;
  /** Zda má zařízení posílat plnou teplotní mapu (`thrmap_on`). */
  thrmap = true;

  /** Adresa /data.json, ze které se právě čte (zdroj `api`). */
  apiUrl: string | null = null;

  private demoTimer: ReturnType<typeof setInterval> | null = null;
  private demoStep = 0;
  private apiTimer: ReturnType<typeof setTimeout> | null = null;
  /** Roste s každým připojením k API; starší rozpracované dotazy se podle něj zahodí. */
  private apiRun = 0;

  private readonly link = new SerialLink({
    onLine: (line) => this.session.ingestLine(line),
    onState: (state, error) => {
      this.state = state;
      if (error) this.error = error;
      if (state === 'connected') {
        this.source = 'serial';
        this.error = null;
        this.session.addLog('info', 'Connected');
        // Mapa je po startu firmwaru vypnutá; zapíná se příkazem stejně jako v Python vieweru.
        // $HELLO odchází jen při startu firmwaru; po připojení si ho vyžádáme znovu.
        void this.send('hello').then(() => this.send(this.thrmap ? 'thrmap_on' : 'thrmap_off'));
      } else if (state === 'disconnected') {
        if (this.source === 'serial') this.session.addLog('info', error ?? 'Disconnected');
        this.source = null;
      } else {
        this.session.addLog('info', 'Connecting…');
      }
    },
  });

  async connectSerial(baudRate: number): Promise<void> {
    if (this.state !== 'disconnected') return;
    this.error = null;
    await this.link.connect(baudRate);
  }

  /** Čte živá data z HTTP API Python vieweru (`amsky-viewer --api`). */
  async connectApi(url: string): Promise<void> {
    if (this.state !== 'disconnected') return;
    const run = ++this.apiRun;
    const converter = new SnapshotConverter();
    this.error = null;
    this.source = 'api';
    this.apiUrl = url;
    this.state = 'connecting';
    this.session.addLog('info', `Connecting to API ${url}…`);

    const poll = async (): Promise<void> => {
      let snapshot: unknown;
      let failure: string | null = null;
      try {
        const response = await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout(API_TIMEOUT_MS) });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        snapshot = await response.json();
      } catch (error) {
        failure = describeApiError(url, error, window.location.protocol);
      }
      if (run !== this.apiRun || this.source !== 'api') return;

      if (failure) {
        if (this.state === 'connecting') {
          // První dotaz neprošel — nemá smysl opakovat, adresa je nejspíš špatně.
          this.error = failure;
          this.session.addLog('info', failure);
          this.source = null;
          this.apiUrl = null;
          this.state = 'disconnected';
          this.session.addLog('info', 'Disconnected');
          return;
        }
        // Výpadek za běhu: zkoušíme dál, stav ukáže „bez dat“.
        if (this.error !== failure) this.session.addLog('info', failure);
        this.error = failure;
      } else {
        if (this.state === 'connecting') {
          this.state = 'connected';
          this.session.addLog('info', 'Connected to API');
        } else if (this.error) {
          this.session.addLog('info', 'API connection restored');
        }
        this.error = null;
        converter.toLines(snapshot).forEach((line) => this.session.ingestLine(line));
      }
      this.apiTimer = setTimeout(() => void poll(), API_POLL_MS);
    };
    await poll();
  }

  startDemo(): void {
    if (this.state !== 'disconnected') return;
    this.error = null;
    this.source = 'demo';
    this.state = 'connected';
    this.session.addLog('info', 'Simulator started — this is not data from a real sensor');
    demoHello().forEach((line) => this.session.ingestLine(line));
    const tick = () => demoTick(this.demoStep++, this.thrmap).forEach((line) => this.session.ingestLine(line));
    tick();
    this.demoTimer = setInterval(tick, 2000);
  }

  async disconnect(): Promise<void> {
    if (this.source === 'demo') {
      if (this.demoTimer) clearInterval(this.demoTimer);
      this.demoTimer = null;
      this.source = null;
      this.state = 'disconnected';
      this.session.addLog('info', 'Simulator stopped');
      return;
    }
    if (this.source === 'api') {
      this.apiRun++;
      if (this.apiTimer) clearTimeout(this.apiTimer);
      this.apiTimer = null;
      this.source = null;
      this.apiUrl = null;
      this.state = 'disconnected';
      this.session.addLog('info', 'Disconnected from API');
      return;
    }
    await this.link.disconnect();
  }

  async send(command: string): Promise<void> {
    const text = command.trim();
    if (!text) return;
    this.session.addLog('tx', `> ${text}`);
    if (this.source === 'demo') {
      this.session.addLog('rx', '# the simulator does not execute commands');
      return;
    }
    if (this.source === 'api') {
      this.session.addLog('info', 'Commands cannot be sent over the HTTP API — it is read-only');
      return;
    }
    try {
      await this.link.send(text);
    } catch (error) {
      this.session.addLog('info', error instanceof Error ? error.message : String(error));
    }
  }

  async setThrmap(enabled: boolean): Promise<void> {
    this.thrmap = enabled;
    // U API o mapě rozhoduje viewer, který drží sériový port.
    if (this.source === 'api') return;
    if (this.state === 'connected') await this.send(enabled ? 'thrmap_on' : 'thrmap_off');
    else this.session.addLog('info', `The thermal map will be turned ${enabled ? 'on' : 'off'} after connecting`);
  }
}

export const live = new LiveController();
