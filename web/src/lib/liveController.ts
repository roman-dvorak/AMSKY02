/**
 * Řídí zdroj živých dat (sériový port nebo simulátor) a plní jím relaci.
 * Žije mimo React, takže spojení přežije přepnutí záložky v aplikaci.
 */
import { demoHello, demoTick } from './demo';
import type { LinkState } from './serial';
import { SerialLink } from './serial';
import { LiveSession } from './session';

export type Source = 'serial' | 'demo' | null;

export class LiveController {
  readonly session = new LiveSession();
  state: LinkState = 'disconnected';
  source: Source = null;
  error: string | null = null;
  /** Zda má zařízení posílat plnou teplotní mapu (`thrmap_on`). */
  thrmap = true;

  private demoTimer: ReturnType<typeof setInterval> | null = null;
  private demoStep = 0;

  private readonly link = new SerialLink({
    onLine: (line) => this.session.ingestLine(line),
    onState: (state, error) => {
      this.state = state;
      if (error) this.error = error;
      if (state === 'connected') {
        this.source = 'serial';
        this.error = null;
        this.session.addLog('info', 'Připojeno');
        // Mapa je po startu firmwaru vypnutá; zapíná se příkazem stejně jako v Python vieweru.
        void this.send(this.thrmap ? 'thrmap_on' : 'thrmap_off');
      } else if (state === 'disconnected') {
        if (this.source === 'serial') this.session.addLog('info', error ?? 'Odpojeno');
        this.source = null;
      } else {
        this.session.addLog('info', 'Připojuji…');
      }
    },
  });

  async connectSerial(baudRate: number): Promise<void> {
    if (this.state !== 'disconnected') return;
    this.error = null;
    await this.link.connect(baudRate);
  }

  startDemo(): void {
    if (this.state !== 'disconnected') return;
    this.error = null;
    this.source = 'demo';
    this.state = 'connected';
    this.session.addLog('info', 'Simulátor spuštěn — data nejsou ze skutečného senzoru');
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
      this.session.addLog('info', 'Simulátor zastaven');
      return;
    }
    await this.link.disconnect();
  }

  async send(command: string): Promise<void> {
    const text = command.trim();
    if (!text) return;
    this.session.addLog('tx', `> ${text}`);
    if (this.source === 'demo') {
      this.session.addLog('rx', '# simulátor příkazy neprovádí');
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
    if (this.state === 'connected') await this.send(enabled ? 'thrmap_on' : 'thrmap_off');
    else this.session.addLog('info', `Teplotní mapa bude po připojení ${enabled ? 'zapnuta' : 'vypnuta'}`);
  }
}

export const live = new LiveController();
