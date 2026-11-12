import { useEffect, useMemo, useRef, useState } from 'react';
import type { ColorRange, PaletteName, SkyLayout } from '../lib/sky';
import { PALETTES, composeSky, isPaletteName, paletteLut } from '../lib/sky';
import { useStoredState } from '../lib/storage';

export interface SkyPanel {
  label: string;
  rows: number;
  cols: number;
  pixels: Float32Array | null;
  /** Doplňující text pod mapou (čas snímku, teplota středu…). */
  caption?: string;
}

export interface SkyViewSettings {
  layout: SkyLayout;
  palette: PaletteName;
}

function isSettings(value: unknown): value is SkyViewSettings {
  const v = value as SkyViewSettings | null;
  return !!v && (v.layout === 'rotated' || v.layout === 'stacked') && isPaletteName(v.palette);
}

/** Uspořádání a paleta jsou společné pro živý pohled i přehrávač. */
export function useSkySettings(): [SkyViewSettings, (next: SkyViewSettings) => void] {
  return useStoredState<SkyViewSettings>('amsky.skyView', { layout: 'rotated', palette: 'thermal' }, isSettings);
}

interface Props {
  panels: SkyPanel[];
  range: ColorRange;
  settings: SkyViewSettings;
}

/** Teplotní mapy senzorů složené do jednoho obrazu se společnou barevnou škálou. */
export function SkyMap({ panels, range, settings }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hover, setHover] = useState<string | null>(null);
  const composite = useMemo(() => composeSky(panels, settings.layout), [panels, settings.layout]);
  const rotated = settings.layout === 'rotated';

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx || !composite) return;
    // Kreslí se 1 px na pixel senzoru; zvětšení bez vyhlazení dělá CSS.
    canvas.width = composite.width;
    canvas.height = composite.height;
    const lut = paletteLut(settings.palette);
    const image = ctx.createImageData(composite.width, composite.height);
    const span = range.max - range.min || 1;
    for (let i = 0; i < composite.data.length; i++) {
      const value = composite.data[i];
      const o = i * 4;
      if (Number.isNaN(value)) {
        image.data[o] = 13;
        image.data[o + 1] = 22;
        image.data[o + 2] = 34;
      } else {
        const level = Math.max(0, Math.min(255, Math.round(((value - range.min) / span) * 255))) * 4;
        image.data[o] = lut[level];
        image.data[o + 1] = lut[level + 1];
        image.data[o + 2] = lut[level + 2];
      }
      image.data[o + 3] = 255;
    }
    ctx.putImageData(image, 0, 0);
  }, [composite, range.min, range.max, settings.palette]);

  if (!composite) return null;

  const handleMove = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.floor(((event.clientX - rect.left) / rect.width) * composite.width);
    const y = Math.floor(((event.clientY - rect.top) / rect.height) * composite.height);
    const at = composite.locate(x, y);
    const panel = at && panels[at.tile];
    if (!at || !panel?.pixels) {
      setHover(null);
      return;
    }
    const value = panel.pixels[at.row * panel.cols + at.col];
    setHover(`${panel.label}  x=${at.col}, y=${at.row}  ${Number.isFinite(value) ? `${value.toFixed(2)} °C` : '—'}`);
  };

  const gradient = `linear-gradient(to top, ${PALETTES[settings.palette].colors.join(', ')})`;

  return (
    <div className="sky-map">
      <div className="sky-panels">
        <div className={`sky-frame ${settings.layout}`} style={{ aspectRatio: `${composite.width} / ${composite.height}` }}>
          <canvas ref={canvasRef} className="sky-canvas" onMouseMove={handleMove} onMouseLeave={() => setHover(null)} />
          {panels.map((panel, index) => {
            const share = 100 / panels.length;
            const style = rotated ? { left: `${index * share}%`, top: 0 } : { left: 0, top: `${index * share}%` };
            return (
              <span key={panel.label} className="sky-tag" style={style}>
                {panel.label}
                {panel.pixels ? '' : ' — no data'}
              </span>
            );
          })}
          {panels.slice(1).map((panel, index) => {
            const at = `${((index + 1) * 100) / panels.length}%`;
            return (
              <span
                key={panel.label}
                className="sky-divider"
                style={rotated ? { left: at, top: 0, bottom: 0, width: 1 } : { top: at, left: 0, right: 0, height: 1 }}
              />
            );
          })}
        </div>
        <div className="sky-scale" aria-label="Temperature colour scale">
          <span>{range.max.toFixed(1)} °C</span>
          <div className="sky-scale-bar" style={{ background: gradient }} />
          <span>{range.min.toFixed(1)} °C</span>
        </div>
      </div>
      <div className="sky-captions">
        {panels.map((panel) => (
          <span key={panel.label}>
            <strong>{panel.label}</strong> {panel.caption ?? (panel.pixels ? '' : 'no data')}
          </span>
        ))}
      </div>
      <div className="sky-hover">{hover ?? 'Hover over the map to read a pixel temperature.'}</div>
    </div>
  );
}

/** Číselné pole, které rozepsanou hodnotu („-", „-2") nepřepisuje pod rukama. */
function NumberField({ value, onCommit, label }: { value: number; onCommit(value: number): boolean; label: string }) {
  const [text, setText] = useState<string | null>(null);
  return (
    <label>
      {label}
      <input
        type="number"
        step="1"
        value={text ?? String(Number(value.toFixed(1)))}
        onChange={(e) => {
          setText(e.target.value);
          const parsed = Number(e.target.value);
          if (e.target.value.trim() !== '' && Number.isFinite(parsed)) onCommit(parsed);
        }}
        onBlur={() => setText(null)}
      />
    </label>
  );
}

/** Ovládání zobrazení mapy: uspořádání, paleta a rozsah barevné škály. */
export function SkyControls({
  settings,
  onSettings,
  range,
  auto,
  autoLabel,
  onRange,
  onAuto,
}: {
  settings: SkyViewSettings;
  onSettings(next: SkyViewSettings): void;
  range: ColorRange;
  auto: boolean;
  /** Co znamená automatika v daném pohledu (aktuální snímek / celý záznam). */
  autoLabel: string;
  onRange(range: ColorRange): void;
  onAuto(): void;
}) {
  const commit = (key: 'min' | 'max') => (value: number) => {
    const next = { ...range, [key]: value };
    if (next.max <= next.min) return false;
    onRange(next);
    return true;
  };
  return (
    <div className="sky-controls">
      <label>
        Layout
        <select value={settings.layout} onChange={(e) => onSettings({ ...settings, layout: e.target.value as SkyLayout })}>
          <option value="rotated">Rotated, side by side</option>
          <option value="stacked">Stacked (sky1 on top)</option>
        </select>
      </label>
      <label>
        Palette
        <select value={settings.palette} onChange={(e) => onSettings({ ...settings, palette: e.target.value as PaletteName })}>
          {Object.entries(PALETTES).map(([name, palette]) => (
            <option key={name} value={name}>
              {palette.label}
            </option>
          ))}
        </select>
      </label>
      <span className="sky-range">
        <NumberField label="Scale from" value={range.min} onCommit={commit('min')} />
        <NumberField label="to" value={range.max} onCommit={commit('max')} />
        <span className="unit">°C</span>
      </span>
      <label className="check">
        <input type="checkbox" checked={auto} onChange={(e) => (e.target.checked ? onAuto() : onRange(range))} />
        Auto ({autoLabel})
      </label>
    </div>
  );
}
