/**
 * Připojení k senzoru přes Web Serial API (Chrome, Edge, Opera na desktopu;
 * stránka musí běžet přes HTTPS nebo na localhostu).
 */

export type LinkState = 'disconnected' | 'connecting' | 'connected';

export interface LinkHandlers {
  onLine(line: string): void;
  onState(state: LinkState, error?: string): void;
}

export function serialSupported(): boolean {
  return typeof navigator !== 'undefined' && 'serial' in navigator;
}

/** Rozdělí proud bajtů na řádky; neúplný konec si drží do příštího bloku. */
export class LineSplitter {
  private buffer = '';
  private decoder = new TextDecoder();

  push(chunk: Uint8Array): string[] {
    this.buffer += this.decoder.decode(chunk, { stream: true });
    const lines = this.buffer.split(/\r\n|\n|\r/);
    this.buffer = lines.pop() ?? '';
    // Pojistka proti nekonečnému řádku (špatná rychlost, šum na lince).
    if (this.buffer.length > 65536) this.buffer = '';
    return lines.filter((line) => line.length > 0);
  }
}

export class SerialLink {
  private port: SerialPort | null = null;
  private reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  private closing = false;
  private readonly encoder = new TextEncoder();

  constructor(private readonly handlers: LinkHandlers) {}

  get connected(): boolean {
    return this.port !== null;
  }

  /** Musí být zavoláno z uživatelského gesta (klik) — prohlížeč ukáže výběr portu. */
  async connect(baudRate: number): Promise<void> {
    if (this.port) return;
    let port: SerialPort;
    try {
      port = await navigator.serial.requestPort();
    } catch {
      return; // uživatel výběr zavřel
    }
    this.handlers.onState('connecting');
    try {
      await port.open({ baudRate });
    } catch (error) {
      this.handlers.onState('disconnected', `Port nelze otevřít: ${message(error)}`);
      return;
    }
    this.port = port;
    this.closing = false;
    this.handlers.onState('connected');
    void this.readLoop(port);
  }

  private async readLoop(port: SerialPort): Promise<void> {
    const splitter = new LineSplitter();
    let failure: string | undefined;
    try {
      // Vnější smyčka: po chybě rámce/přetečení jde čtení obnovit novým readerem.
      while (port.readable && !this.closing) {
        this.reader = port.readable.getReader();
        try {
          for (;;) {
            const { value, done } = await this.reader.read();
            if (done) break;
            if (value) for (const line of splitter.push(value)) this.handlers.onLine(line);
          }
        } finally {
          this.reader.releaseLock();
          this.reader = null;
        }
      }
    } catch (error) {
      if (!this.closing) failure = `Spojení přerušeno: ${message(error)}`;
    }
    try {
      await port.close();
    } catch {
      /* port už je pryč (odpojený kabel) */
    }
    if (this.port === port) this.port = null;
    this.handlers.onState('disconnected', failure);
  }

  async send(command: string): Promise<void> {
    const writable = this.port?.writable;
    if (!writable) throw new Error('Zařízení není připojeno');
    const writer = writable.getWriter();
    try {
      await writer.write(this.encoder.encode(`${command}\n`));
    } finally {
      writer.releaseLock();
    }
  }

  async disconnect(): Promise<void> {
    if (!this.port) return;
    this.closing = true;
    try {
      await this.reader?.cancel();
    } catch {
      /* ignore */
    }
  }
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
