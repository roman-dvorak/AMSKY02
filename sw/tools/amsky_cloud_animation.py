"""Animace oblačnosti přes senzor AMSKY01 s grafy.

Vizualizace obsahuje:
  - Tepelnou mapu oblohy (12×16 px) s mraky přecházejícími přes senzor
  - Graf oblačnosti v zenitu (střed zorného pole)
  - Graf průměrné oblačnosti, min, max a medián

Spuštění:
    python tools/amsky_cloud_animation.py ../../doc/data/AMSKY01_20260103_22.h5
    python tools/amsky_cloud_animation.py ../../doc/data/AMSKY01_20260103_*.h5 --vmin -30 --vmax 5
    python tools/amsky_cloud_animation.py ../../doc/data/AMSKY01_20260103_22.h5 --out cloud_demo.mp4

Závislosti:
    pip install h5py numpy matplotlib tqdm
    apt install ffmpeg
"""

# %% ── imports ────────────────────────────────────────────────────────────────
import argparse
import glob
import os
import sys
from datetime import datetime, timezone

import h5py
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.animation import FuncAnimation, FFMpegWriter
import matplotlib.dates as mdates

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

plt.style.use("dark_background")

# %% ── výchozí parametry ─────────────────────────────────────────────────────
VMIN_DEFAULT = -30.0    # °C — jasná obloha
VMAX_DEFAULT =   5.0    # °C — mraky
FPS          = 20
FRAME_STEP   = 1
BITRATE      = 2500
LOCATION     = "AMSKY01"

# Zenith = střed mřížky 12×16 (řádky 5–6, sloupce 7–8)
ZENITH_ROWS = slice(5, 7)
ZENITH_COLS = slice(7, 9)


# %% ── parsování argumentů ───────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="Animace oblačnosti AMSKY01 s grafy")
    p.add_argument("files", nargs="+", metavar="FILE",
                   help="HDF5 soubor(y), lze použít glob vzory")
    p.add_argument("--vmin",  type=float, default=VMIN_DEFAULT,
                   help=f"min. teplota stupnice [°C] (default {VMIN_DEFAULT})")
    p.add_argument("--vmax",  type=float, default=VMAX_DEFAULT,
                   help=f"max. teplota stupnice [°C] (default {VMAX_DEFAULT})")
    p.add_argument("--fps",   type=int,   default=FPS,
                   help=f"snímků za sekundu (default {FPS})")
    p.add_argument("--step",  type=int,   default=FRAME_STEP,
                   help=f"brat každý N-tý snímek (default {FRAME_STEP})")
    p.add_argument("--out",   type=str,   default=None,
                   help="výstupní soubor (default: automaticky)")
    p.add_argument("--location", type=str, default=LOCATION,
                   help=f"název místa v titulku (default: {LOCATION})")
    return p.parse_args()


# %% ── načtení dat ───────────────────────────────────────────────────────────
def load_hdf5_files(file_patterns):
    """Načte a seřadí sky data z HDF5 souborů."""
    paths = []
    for pat in file_patterns:
        expanded = sorted(glob.glob(pat))
        if expanded:
            paths.extend(expanded)
        elif os.path.exists(pat):
            paths.append(pat)

    if not paths:
        print(f"CHYBA: Žádné soubory nenalezeny: {file_patterns}", file=sys.stderr)
        sys.exit(1)

    print(f"Načítám {len(paths)} soubor(ů):")
    sky_data_list, sky_time_list = [], []

    for path in paths:
        print(f"  {os.path.basename(path)}")
        with h5py.File(path, "r") as f:
            if "sky1" in f:
                sky_data_list.append(f["sky1"]["data"][:])
                sky_time_list.append(f["sky1"]["time"][:])
            elif "sky" in f:
                sky_data_list.append(f["sky"]["data"][:])
                sky_time_list.append(f["sky"]["time"][:])

    sky_data = np.concatenate(sky_data_list, axis=0)
    sky_time = np.concatenate(sky_time_list)

    # Seřadit podle času
    order = np.argsort(sky_time)
    sky_data = sky_data[order]
    sky_time = sky_time[order]

    n = len(sky_data)
    if n >= 2:
        dt0 = datetime.fromtimestamp(sky_time[0]  / 1e9, tz=timezone.utc)
        dt1 = datetime.fromtimestamp(sky_time[-1] / 1e9, tz=timezone.utc)
        print(f"\nCelkem: {n} snímků")
        print(f"Rozsah: {dt0.strftime('%Y-%m-%d %H:%M:%S')} — {dt1.strftime('%H:%M:%S')} UTC")
        print(f"Délka:  {(sky_time[-1]-sky_time[0])/1e9/60:.1f} min")

    return sky_data, sky_time


# %% ── výpočet statistik ─────────────────────────────────────────────────────
def compute_sky_stats(sky_data):
    """Spočítá statistiky teploty oblohy pro každý snímek.

    Vrací: zenith, mean, min, max, median  (vše v °C)
    """
    n = len(sky_data)
    zenith = np.empty(n)
    mean   = np.empty(n)
    mn     = np.empty(n)
    mx     = np.empty(n)
    median = np.empty(n)

    for i in range(n):
        frame = sky_data[i]
        zenith[i] = np.mean(frame[ZENITH_ROWS, ZENITH_COLS])
        mean[i]   = np.mean(frame)
        mn[i]     = np.min(frame)
        mx[i]     = np.max(frame)
        median[i] = np.median(frame)

    return zenith, mean, mn, mx, median


# %% ── výstupní jméno ────────────────────────────────────────────────────────
def build_output_filename(input_files, out_arg):
    if out_arg:
        return out_arg
    base = os.path.basename(input_files[0])
    stem = os.path.splitext(base)[0]
    if len(input_files) > 1:
        stem = stem.rsplit("_", 1)[0] + "_all"
    return stem + "_cloud_anim.mp4"


# %% ── export videa ──────────────────────────────────────────────────────────
def export_video(sky_data, sky_time, vmin, vmax, fps, step,
                 output_file, location):
    """Vykreslí a uloží animaci s tepelnou mapou a grafy oblačnosti."""

    frame_indices = list(range(0, len(sky_data), step))
    n_frames = len(frame_indices)

    print(f"\nVýpočet statistik...")
    zenith, sky_mean, sky_min, sky_max, sky_median = \
        compute_sky_stats(sky_data)

    # Časová osa jako datetime
    datetimes = [datetime.fromtimestamp(t / 1e9, tz=timezone.utc) for t in sky_time]
    time_nums = mdates.date2num(datetimes)

    print(f"Export: {n_frames} snímků @ {fps} fps → {output_file}")
    video_s = n_frames / fps
    print(f"Délka videa: {video_s:.1f} s ({video_s/60:.1f} min)")

    # ── layout ────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(16, 10), layout="constrained")
    fig.patch.set_facecolor("#111111")

    gs = gridspec.GridSpec(2, 2, height_ratios=[1.2, 1],
                           width_ratios=[1, 1.5],
                           hspace=0.12, wspace=0.12,
                           figure=fig)

    ax_map   = fig.add_subplot(gs[0, 0])   # tepelná mapa
    ax_zen   = fig.add_subplot(gs[0, 1])   # zenith
    ax_stats = fig.add_subplot(gs[1, :])   # statistiky

    for ax in [ax_map, ax_zen, ax_stats]:
        ax.set_facecolor("#111111")

    # ── tepelná mapa ──────────────────────────────────────────────────────
    im = ax_map.imshow(sky_data[frame_indices[0]], cmap="inferno",
                       vmin=vmin, vmax=vmax, origin="lower",
                       aspect="auto", interpolation="nearest")

    # Označení zenitu
    ax_map.plot([7, 8], [5, 5], color="cyan", linewidth=0.8, alpha=0.6)
    ax_map.plot([7, 8], [6, 6], color="cyan", linewidth=0.8, alpha=0.6)
    ax_map.plot([7, 7], [5, 6], color="cyan", linewidth=0.8, alpha=0.6)
    ax_map.plot([8, 8], [5, 6], color="cyan", linewidth=0.8, alpha=0.6)

    cbar = fig.colorbar(im, ax=ax_map, fraction=0.046, pad=0.04)
    cbar.set_label("Teplota [°C]", fontsize=9, color="#cccccc")
    cbar.ax.tick_params(labelsize=8)
    # Popisky Jasno/Zataženo
    mid = (vmin + vmax) / 2
    cbar.ax.text(2.8, vmax, "Zataženo", va="top",    ha="left", fontsize=8, color="#cccccc")
    cbar.ax.text(2.8, mid,  "Polojasno",va="center", ha="left", fontsize=8, color="#cccccc")
    cbar.ax.text(2.8, vmin, "Jasno",    va="bottom", ha="left", fontsize=8, color="#cccccc")

    ax_map.set_xlabel("Pixel (x)", fontsize=9, color="#aaaaaa")
    ax_map.set_ylabel("Pixel (y)", fontsize=9, color="#aaaaaa")
    ax_map.tick_params(colors="#aaaaaa")

    dt0_str = datetimes[frame_indices[0]].strftime('%Y-%m-%d %H:%M:%S UTC')
    title_map = ax_map.set_title(
        f"Tepelná mapa oblohy — {location}\n{dt0_str}",
        color="white", fontsize=11
    )

    # Y-osa – rozsah teplot pro grafy (s malou rezervou)
    y_lo = vmin - 2
    y_hi = vmax + 2

    # ── graf zenitu ───────────────────────────────────────────────────────
    zen_line, = ax_zen.plot([], [], color="#00ddff", linewidth=1.5, label="Zenith")
    zen_marker, = ax_zen.plot([], [], "o", color="#00ddff", markersize=6)

    ax_zen.set_xlim(time_nums[frame_indices[0]], time_nums[frame_indices[-1]])
    ax_zen.set_ylim(y_lo, y_hi)
    ax_zen.set_ylabel("Teplota oblohy [°C]", fontsize=10, color="#aaaaaa")
    ax_zen.set_title("Teplota oblohy v zenitu", color="white", fontsize=11)
    ax_zen.grid(True, alpha=0.2)
    ax_zen.tick_params(colors="#aaaaaa")
    ax_zen.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax_zen.legend(loc="upper left", fontsize=9)

    zen_value_text = ax_zen.text(
        0.98, 0.95, "", transform=ax_zen.transAxes,
        color="#00ddff", fontsize=12, fontweight="bold",
        va="top", ha="right", fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#00000088", edgecolor="none")
    )

    # ── graf statistik ────────────────────────────────────────────────────
    mean_line, = ax_stats.plot([], [], color="#ff8800", linewidth=1.8, label="Průměr")
    min_line,  = ax_stats.plot([], [], color="#44aaff", linewidth=1.0, linestyle="--", label="Min")
    max_line,  = ax_stats.plot([], [], color="#ff4444", linewidth=1.0, linestyle="--", label="Max")
    med_line,  = ax_stats.plot([], [], color="#44ff44", linewidth=1.2, linestyle="-.", label="Medián")

    # Výplň min–max
    fill_collection = ax_stats.fill_between([], [], [], alpha=0.1, color="#888888")

    ax_stats.set_xlim(time_nums[frame_indices[0]], time_nums[frame_indices[-1]])
    ax_stats.set_ylim(y_lo, y_hi)
    ax_stats.set_xlabel("Čas (UTC)", fontsize=10, color="#aaaaaa")
    ax_stats.set_ylabel("Teplota oblohy [°C]", fontsize=10, color="#aaaaaa")
    ax_stats.set_title("Statistiky teploty oblohy (celé zorné pole)", color="white", fontsize=11)
    ax_stats.grid(True, alpha=0.2)
    ax_stats.tick_params(colors="#aaaaaa")
    ax_stats.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax_stats.legend(loc="upper left", fontsize=9, ncol=4)

    stats_text = ax_stats.text(
        0.98, 0.95, "", transform=ax_stats.transAxes,
        color="#ff8800", fontsize=10, va="top", ha="right",
        fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#00000088", edgecolor="none")
    )

    # ── animační funkce ───────────────────────────────────────────────────
    def update(i):
        fi = frame_indices[i]

        # Tepelná mapa
        im.set_data(sky_data[fi])
        dt_str = datetimes[fi].strftime('%Y-%m-%d %H:%M:%S UTC')
        title_map.set_text(f"Tepelná mapa oblohy — {location}\n{dt_str}")

        # Data do aktuálního snímku
        idx_slice = frame_indices[:i+1]
        t_slice = [time_nums[j] for j in idx_slice]

        # Zenith
        zen_vals = zenith[idx_slice]
        zen_line.set_data(t_slice, zen_vals)
        zen_marker.set_data([t_slice[-1]], [zen_vals[-1]])
        zen_value_text.set_text(f"{zen_vals[-1]:.1f} °C")

        # Statistiky
        m_vals   = sky_mean[idx_slice]
        mn_vals  = sky_min[idx_slice]
        mx_vals  = sky_max[idx_slice]
        med_vals = sky_median[idx_slice]

        mean_line.set_data(t_slice, m_vals)
        min_line.set_data(t_slice, mn_vals)
        max_line.set_data(t_slice, mx_vals)
        med_line.set_data(t_slice, med_vals)

        # Aktualizace fill_between – nutno odstranit starou a přidat novou
        nonlocal fill_collection
        fill_collection.remove()
        fill_collection = ax_stats.fill_between(
            t_slice, mn_vals, mx_vals, alpha=0.1, color="#888888"
        )

        stats_text.set_text(
            f"Avg {m_vals[-1]:.1f}°C  Med {med_vals[-1]:.1f}°C  "
            f"Min {mn_vals[-1]:.1f}°C  Max {mx_vals[-1]:.1f}°C"
        )

        return [im, title_map, zen_line, zen_marker, zen_value_text,
                mean_line, min_line, max_line, med_line, fill_collection,
                stats_text]

    anim = FuncAnimation(fig, update, frames=n_frames,
                         interval=1000 / fps, blit=False)

    writer = FFMpegWriter(fps=fps, metadata={"artist": "AMSKY01"}, bitrate=BITRATE)

    if HAS_TQDM:
        pbar = tqdm(total=n_frames, desc="Rendering")
        def progress(current, total):
            pbar.update(1)
        anim.save(output_file, writer=writer, progress_callback=progress)
        pbar.close()
    else:
        def progress(current, total):
            if current % 100 == 0:
                print(f"  {current}/{total} snímků...")
        anim.save(output_file, writer=writer, progress_callback=progress)

    plt.close(fig)
    size_mb = os.path.getsize(output_file) / 1e6
    print(f"Hotovo: {output_file}  ({size_mb:.1f} MB)")


# %% ── main ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    args = parse_args()

    sky_data, sky_time = load_hdf5_files(args.files)

    output_file = build_output_filename(args.files, args.out)

    export_video(
        sky_data, sky_time,
        vmin=args.vmin,
        vmax=args.vmax,
        fps=args.fps,
        step=args.step,
        output_file=output_file,
        location=args.location,
    )
