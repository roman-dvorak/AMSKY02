"""AMSKY TUI — real-time terminal dashboard

Polls the HTTP JSON API served by amsky_viewer.py running with --headless --api.

Dependencies:
    pip install rich numpy

Usage:
    python amsky_tui.py
    python amsky_tui.py --url http://HOST:8080/data.json
    python amsky_tui.py --interval 2.0
    python amsky_tui.py --vmin -30 --vmax 10
    python amsky_tui.py --ta-coeff 0.5   # odečti 0.5 * Ta od každého pixelu
"""

import argparse
import json
import time
from datetime import datetime
from urllib.request import urlopen
from urllib.error import URLError

import numpy as np
from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Rozměr teplotní mapy podle počtu pixelů: AMSKY02 (MLX90642) 32×24,
# starší AMSKY01 (MLX90641) 16×12.
MAP_SHAPES = {768: (24, 32), 192: (12, 16)}
LEGEND_STEPS = 16


def _temp_to_ansi256(temp: float, vmin: float, vmax: float) -> int:
    """Map temperature to ANSI 256-color index (blue=cold → red=hot)."""
    span = vmax - vmin
    t = max(0.0, min(1.0, (temp - vmin) / span)) if span > 0 else 0.5

    if t < 0.25:
        s = t / 0.25
        r, g, b = 0, round(s * 5), 5
    elif t < 0.5:
        s = (t - 0.25) / 0.25
        r, g, b = 0, 5, round((1 - s) * 5)
    elif t < 0.75:
        s = (t - 0.5) / 0.25
        r, g, b = round(s * 5), 5, 0
    else:
        s = (t - 0.75) / 0.25
        r, g, b = 5, round((1 - s) * 5), 0

    return 16 + 36 * r + 6 * g + b


def _render_legend(vmin: float, vmax: float) -> Text:
    text = Text()
    text.append(f"  {vmin:.1f}°C ", style="dim")
    for i in range(LEGEND_STEPS):
        ci = _temp_to_ansi256(vmin + (vmax - vmin) * i / (LEGEND_STEPS - 1), vmin, vmax)
        text.append("█", style=f"color({ci})")
    text.append(f" {vmax:.1f}°C\n", style="dim")
    return text


def _render_sensor_pixels(arr: np.ndarray, vmin: float, vmax: float, label: str) -> Text:
    text = Text()
    text.append(f" {label}  ", style="bold white")
    mean, lo, hi = float(arr.mean()), float(arr.min()), float(arr.max())
    text.append(f"min={lo:.1f}  mean={mean:.1f}  max={hi:.1f} °C\n", style="dim")

    rows, cols = arr.shape
    for row in range(0, rows, 2):
        text.append("  ")
        for col in range(cols):
            top = arr[row, col]
            bot = arr[row + 1, col] if (row + 1) < rows else top
            ci_top = _temp_to_ansi256(top, vmin, vmax)
            ci_bot = _temp_to_ansi256(bot, vmin, vmax)
            text.append("▄", style=f"color({ci_bot}) on color({ci_top})")
        text.append("\n")

    return text


def render_heatmap_pair(
    data: dict,
    vmin_fixed: float | None,
    vmax_fixed: float | None,
    ta_coeff: float,
) -> Text:
    """Render both sensors with shared scale and a single legend."""
    flat1 = data.get("thrmap1")
    flat2 = data.get("thrmap2")
    ta1 = (data.get("mlx1") or {}).get("ta") or 0.0
    ta2 = (data.get("mlx2") or {}).get("ta") or 0.0

    no_data = Text()

    def _to_arr(flat, ta):
        shape = MAP_SHAPES.get(len(flat)) if flat else None
        if shape is None:
            return None
        arr = np.array(flat, dtype=np.float32).reshape(shape)
        if ta_coeff != 0.0:
            arr = arr - ta * ta_coeff
        return arr

    arr1 = _to_arr(flat1, ta1)
    arr2 = _to_arr(flat2, ta2)

    if arr1 is None and arr2 is None:
        no_data.append("  [no data]\n", style="dim")
        return no_data

    # Shared scale from both sensors
    all_vals = np.concatenate([
        a.ravel() for a in (arr1, arr2) if a is not None
    ])
    vmin = vmin_fixed if vmin_fixed is not None else float(all_vals.min())
    vmax = vmax_fixed if vmax_fixed is not None else float(all_vals.max())
    if vmax <= vmin:
        vmax = vmin + 1.0

    text = Text()

    # Single shared legend
    text.append_text(_render_legend(vmin, vmax))

    # Ta correction info
    if ta_coeff != 0.0:
        text.append(f"  Ta korekce: ×{ta_coeff}  (S1 Ta={ta1:.1f}°C, S2 Ta={ta2:.1f}°C)\n",
                    style="dim yellow")

    # Sensor 1
    if arr1 is not None:
        text.append_text(_render_sensor_pixels(arr1, vmin, vmax, "Senzor 1"))
    else:
        text.append(" Senzor 1  [dim][no data][/dim]\n")

    # Sensor 2 directly below (no blank line)
    if arr2 is not None:
        text.append_text(_render_sensor_pixels(arr2, vmin, vmax, "Senzor 2"))
    else:
        text.append(" Senzor 2  [dim][no data][/dim]\n")

    return text


def _fmt(val, fmt="{:.2f}", suffix="") -> str:
    if val is None:
        return "[dim]—[/dim]"
    try:
        return fmt.format(val) + suffix
    except Exception:
        return str(val)


def _add_light_rows(table: Table, prefix: str, li: dict) -> None:
    table.add_section()
    sqm = li.get("sqm")
    quality = li.get("quality")
    quality_style = {
        "OK": "green", "LOW_SIGNAL": "yellow",
        "IR_DOMINATED": "yellow", "VISIBLE_UNRELIABLE": "red",
        "SATURATED": "red", "ERROR": "red",
    }.get(quality or "", "dim")
    quality_str = f"[{quality_style}]{quality}[/{quality_style}]" if quality else "[dim]—[/dim]"

    sqm_str = f"{sqm:.3f} mag/arcsec²" if sqm is not None else "[dim]—[/dim]"
    table.add_row(prefix + "SQM", sqm_str)
    table.add_row(prefix + "TSL Quality", quality_str)
    ir_ratio = li.get("ir_ratio")
    table.add_row(prefix + "IR ratio", f"{ir_ratio:.3f}" if ir_ratio is not None else "[dim]—[/dim]")
    table.add_row(prefix + "Lux", _fmt(li.get("lux"), fmt="{:.6f}"))
    table.add_row(
        prefix + "TSL Full / IR (raw)",
        f"{_fmt(li.get('full'), fmt='{:.0f}')} / {_fmt(li.get('ir'), fmt='{:.0f}')}",
    )
    n_avg = li.get("n_avg")
    avg_label = f"TSL Full / IR (avg n={n_avg})" if n_avg else "TSL Full / IR (avg)"
    table.add_row(
        prefix + avg_label,
        f"{_fmt(li.get('full_avg'), fmt='{:.1f}')} / {_fmt(li.get('ir_avg'), fmt='{:.1f}')}",
    )
    table.add_row(
        prefix + "TSL Gain / Expo",
        f"{li.get('gain') or '—'} / {li.get('itime') or '—'}",
    )


def build_data_table(data: dict) -> Table:
    table = Table(
        show_header=True,
        header_style="bold cyan",
        box=box.SIMPLE,
        expand=True,
        show_edge=False,
    )
    table.add_column("Parametr", style="dim", no_wrap=True)
    table.add_column("Hodnota", justify="right")

    h = data.get("hygro", {})
    table.add_row("SHT4x Teplota", _fmt(h.get("temp"), suffix=" °C"))
    table.add_row("SHT4x Vlhkost", _fmt(h.get("rh"), suffix=" %"))
    table.add_row("Rosný bod", _fmt(h.get("dew_point"), suffix=" °C"))

    # AMSKY02 má dva kanály TSL2591 (light0/light1), starší AMSKY01 jeden (light).
    lights = [(f"L{ch} ", data[f"light{ch}"]) for ch in (0, 1) if data.get(f"light{ch}")]
    if not lights:
        lights = [("", data.get("light", {}))]
    for prefix, li in lights:
        _add_light_rows(table, prefix, li)

    for sid in (1, 2):
        table.add_section()
        m = data.get(f"mlx{sid}", {})
        table.add_row(f"[bold]MLX{sid}[/bold] Ta", _fmt(m.get("ta"), suffix=" °C"))
        table.add_row(f"[bold]MLX{sid}[/bold] Vdd", _fmt(m.get("vdd"), fmt="{:.3f}", suffix=" V"))
        c = data.get(f"cloud{sid}", {})
        table.add_row(f"S{sid} TL / TR", f"{_fmt(c.get('tl'))} / {_fmt(c.get('tr'))} °C")
        table.add_row(f"S{sid} BL / BR", f"{_fmt(c.get('bl'))} / {_fmt(c.get('br'))} °C")
        table.add_row(f"S{sid} Center", _fmt(c.get("center"), suffix=" °C"))

    return table


def build_layout(
    data: dict | None,
    error: str | None,
    url: str,
    interval: float,
    vmin_fixed: float | None,
    vmax_fixed: float | None,
    ta_coeff: float,
) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=1),
    )

    ts = (data or {}).get("timestamp") or "—"
    hdr = Text()
    hdr.append("AMSKY TUI", style="bold cyan")
    device = (data or {}).get("device") or {}
    if device.get("serial_number"):
        hdr.append(f"  •  {device.get('device_model', '')} SN {device['serial_number']}", style="dim")
    hdr.append(f"  •  {url}", style="dim")
    hdr.append(f"  •  {interval:.1f}s", style="dim")
    if vmin_fixed is not None or vmax_fixed is not None:
        hdr.append(f"  •  rozsah: {vmin_fixed}…{vmax_fixed} °C", style="dim yellow")
    if ta_coeff != 0.0:
        hdr.append(f"  •  Ta×{ta_coeff}", style="dim yellow")
    layout["header"].update(Panel(hdr))

    if error or data is None:
        layout["body"].update(
            Panel(
                f"[red]Chyba připojení:[/red]\n{error or 'žádná data'}\n\n"
                "Spusťte headless viewer s přepínačem [bold]--api[/bold]:\n"
                "  python amsky_viewer.py --port /dev/ttyACM0 --headless --api",
                title="[red]Chyba[/red]",
            )
        )
    else:
        layout["body"].split_row(
            Layout(name="obraz", minimum_size=38),
            Layout(name="data", minimum_size=38),
        )
        img_content = render_heatmap_pair(data, vmin_fixed, vmax_fixed, ta_coeff)
        layout["obraz"].update(Panel(img_content, title="[bold]Obraz[/bold]", border_style="blue"))
        layout["data"].update(
            Panel(build_data_table(data), title="[bold]Data[/bold]", border_style="green")
        )

    now = datetime.now().strftime("%H:%M:%S")
    layout["footer"].update(
        Text(f" {now}  |  data: {ts}  |  Ctrl+C = konec", style="dim")
    )
    return layout


def fetch(url: str) -> tuple:
    try:
        with urlopen(url, timeout=3) as resp:
            return json.loads(resp.read()), None
    except URLError as e:
        return None, str(e)
    except Exception as e:
        return None, str(e)


def main():
    parser = argparse.ArgumentParser(description="AMSKY TUI — real-time terminal dashboard")
    parser.add_argument("--url", default="http://localhost:8080/data.json",
                        help="URL JSON API (default: http://localhost:8080/data.json)")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="interval obnovy v sekundách (default: 1.0)")
    parser.add_argument("--vmin", type=float, default=None,
                        help="pevné minimum teplotní škály [°C]")
    parser.add_argument("--vmax", type=float, default=None,
                        help="pevné maximum teplotní škály [°C]")
    parser.add_argument("--ta-coeff", type=float, default=0.0, metavar="K",
                        help="od každého pixelu odečti K × Ta senzoru (default: 0.0 = vypnuto)")
    args = parser.parse_args()

    console = Console()
    with Live(console=console, screen=True, refresh_per_second=4) as live:
        try:
            while True:
                data, error = fetch(args.url)
                live.update(build_layout(
                    data, error, args.url, args.interval,
                    args.vmin, args.vmax, args.ta_coeff,
                ))
                time.sleep(args.interval)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
