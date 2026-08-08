"""Export AMSKY01 HDF5 log souborů do MP4 videa.

Spuštění:
    python tools/amsky_h5_to_video.py AMSKY01_20260502_18.h5
    python tools/amsky_h5_to_video.py ../../doc/data/AMSKY01_20260103_22.h5 --vmin -30 --vmax 5
    python tools/amsky_h5_to_video.py ../../doc/data/AMSKY01_20260103_*.h5  # celá noc

Závislosti:
    pip install h5py numpy matplotlib tqdm
    apt install ffmpeg   (nebo conda install ffmpeg)
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
matplotlib.use("Agg")            # bez GUI – nutné pro render do souboru
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.animation import FuncAnimation, FFMpegWriter

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

plt.style.use("dark_background")

# %% ── parametry ──────────────────────────────────────────────────────────────
# Tyto hodnoty lze přepsat z příkazové řádky (--vmin / --vmax).
# Škála zůstane fixní pro celé video – co je mimo rozsah se ořízne.

VMIN_DEFAULT  = -30.0   # °C  — zřetelně jasná obloha
VMAX_DEFAULT  =   5.0   # °C  — zataženo / teplé mraky

FPS           = 20      # snímků za sekundu ve výstupním videu
FRAME_STEP    = 1       # berte každý N-tý snímek (1 = všechny)
BITRATE       = 2000    # kbps pro FFMpeg
LOCATION      = "AMSKY01"

# %% ── parsování argumentů ────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="Převod AMSKY01 HDF5 logu na MP4 video")
    p.add_argument("files", nargs="+", metavar="FILE",
                   help="HDF5 soubor(y), lze použít glob vzory")
    p.add_argument("--vmin",  type=float, default=VMIN_DEFAULT,
                   help=f"min. teplota stupnice [°C] (default {VMIN_DEFAULT})")
    p.add_argument("--vmax",  type=float, default=VMAX_DEFAULT,
                   help=f"max. teplota stupnice [°C] (default {VMAX_DEFAULT})")
    p.add_argument("--fps",   type=int,   default=FPS,
                   help=f"snímků za sekundu výstupního videa (default {FPS})")
    p.add_argument("--step",  type=int,   default=FRAME_STEP,
                   help=f"brat každý N-tý snímek (default {FRAME_STEP})")
    p.add_argument("--out",   type=str,   default=None,
                   help="výstupní soubor (default: automaticky z názvu vstupu)")
    p.add_argument("--location", type=str, default=LOCATION,
                   help=f"název místa pro titulek (default: {LOCATION})")
    p.add_argument("--preview", action="store_true",
                   help="zobraz náhled prostředního snímku (vyžaduje display)")
    return p.parse_args()


# %% ── načtení dat ────────────────────────────────────────────────────────────
def load_hdf5_files(file_patterns):
    """Načte a seřadí data z jednoho nebo více HDF5 souborů."""
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
    sky1_data_list, sky1_time_list, sky1_temp_list = [], [], []
    sky2_data_list, sky2_time_list = [], []
    hygro_temp_list, hygro_hum_list, hygro_time_list = [], [], []
    ROWS, COLS = 12, 16

    for path in paths:
        print(f"  {os.path.basename(path)}")
        with h5py.File(path, "r") as f:
            # Nový formát /sky1+/sky2; starý /sky (jen senzor 1)
            if "sky1" in f:
                sky1_data_list.append(f["sky1"]["data"][:])
                sky1_time_list.append(f["sky1"]["time"][:])
                sky1_temp_list.append(f["sky1"]["temp"][:])
                if "sky2" in f and len(f["sky2"]["data"]) > 0:
                    sky2_data_list.append(f["sky2"]["data"][:])
                    sky2_time_list.append(f["sky2"]["time"][:])
            else:
                sky1_data_list.append(f["sky"]["data"][:])
                sky1_time_list.append(f["sky"]["time"][:])
                sky1_temp_list.append(f["sky"]["temp"][:])

            if "hygro" in f:
                hygro_temp_list.append(f["hygro"]["temp"][:])
                hygro_hum_list.append(f["hygro"]["hum"][:])
                hygro_time_list.append(f["hygro"]["time"][:])

    sky1_data = np.concatenate(sky1_data_list, axis=0)
    sky1_time = np.concatenate(sky1_time_list)

    has_sky2 = len(sky2_data_list) > 0
    if has_sky2:
        sky2_data = np.concatenate(sky2_data_list, axis=0)
        sky2_time = np.concatenate(sky2_time_list)
        # Seřadit
        o2 = np.argsort(sky2_time)
        sky2_data, sky2_time = sky2_data[o2], sky2_time[o2]
    else:
        sky2_data = np.full((0, ROWS, COLS), np.nan, dtype=np.float32)
        sky2_time = np.array([], dtype=np.int64)

    # Seřadit senzor 1 podle času
    o1 = np.argsort(sky1_time)
    sky1_data = sky1_data[o1]
    sky1_time = sky1_time[o1]

    hygro_temp = np.concatenate(hygro_temp_list) if hygro_temp_list else None
    hygro_hum  = np.concatenate(hygro_hum_list)  if hygro_hum_list  else None
    hygro_time = np.concatenate(hygro_time_list) if hygro_time_list else None

    n1, n2 = len(sky1_data), len(sky2_data)
    print(f"\nCelkem: S1={n1} snímků, S2={n2} snímků"
          + (" (dvojité rozlišení 12×32)" if has_sky2 else " (jen S1, 12×16)"))
    if len(sky1_time) >= 2:
        dt0 = datetime.fromtimestamp(sky1_time[0]  / 1e9, tz=timezone.utc)
        dt1 = datetime.fromtimestamp(sky1_time[-1] / 1e9, tz=timezone.utc)
        print(f"Časový rozsah: {dt0.strftime('%Y-%m-%d %H:%M:%S')} — {dt1.strftime('%H:%M:%S')} UTC")
        print(f"Délka záznamu: {(sky1_time[-1]-sky1_time[0])/1e9/60:.1f} min")

    return (sky1_data, sky1_time, sky2_data, sky2_time,
            hygro_temp, hygro_hum, hygro_time)


# %% ── náhled jednoho snímku ──────────────────────────────────────────────────
def make_combined_frame(sky1_data, sky1_time, sky2_data, sky2_time, idx):
    """Sestaví kombinovaný snímek 12×32 (S1 vlevo, S2 vpravo) pro daný index S1."""
    f1 = sky1_data[idx]
    ts = sky1_time[idx]
    if len(sky2_time) > 0:
        si2 = min(int(np.searchsorted(sky2_time, ts)), len(sky2_data) - 1)
        f2 = sky2_data[si2]
    else:
        f2 = np.full_like(f1, np.nan)
    return np.hstack([f1, f2])   # (12, 32)


def preview_frame(sky1_data, sky1_time, sky2_data, sky2_time, frame_idx, vmin, vmax, location):
    """Zobrazí jeden snímek – volitelný krok pro kontrolu."""
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt2
    plt2.style.use("dark_background")

    frame = make_combined_frame(sky1_data, sky1_time, sky2_data, sky2_time, frame_idx)
    ts_ns = sky1_time[frame_idx]
    dt    = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)

    fig, ax = plt2.subplots(figsize=(14, 6))
    im = ax.imshow(frame, cmap="inferno", vmin=vmin, vmax=vmax,
                   origin="lower", aspect="auto")
    cbar = plt2.colorbar(im, ax=ax, label="Teplota [°C]")
    _add_colorbar_labels(cbar, vmin, vmax)
    ax.set_title(f"Sky Temperature — {location}\n{dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    ax.axvline(x=15.5, color="#555555", linewidth=0.8, linestyle="--")  # dělítko senzorů
    ax.set_xlabel("Pixel (x)  [S1: 0–15 | S2: 16–31]")
    ax.set_ylabel("Pixel (y)")
    plt2.tight_layout()
    plt2.show()


def _add_colorbar_labels(cbar, vmin, vmax):
    """Přidá popisky Jasno/Zataženo ke colorbar."""
    mid = (vmin + vmax) / 2
    cbar.ax.text(2.8, vmax, "Zataženo", va="top",    ha="left", fontsize=8, color="#cccccc")
    cbar.ax.text(2.8, mid,  "Polojasno", va="center", ha="left", fontsize=8, color="#cccccc")
    cbar.ax.text(2.8, vmin, "Jasno",     va="bottom", ha="left", fontsize=8, color="#cccccc")


# %% ── export videa ───────────────────────────────────────────────────────────
def build_output_filename(input_files, out_arg):
    if out_arg:
        return out_arg
    # Odvoď jméno ze vstupního souboru
    base = os.path.basename(input_files[0])
    stem = os.path.splitext(base)[0]
    if len(input_files) > 1:
        stem = stem.rsplit("_", 1)[0]  # odstraň hodinu, zůstane datum
        stem += "_all"
    return stem + ".mp4"


def export_video(sky1_data, sky1_time, sky2_data, sky2_time,
                 hygro_temp, hygro_hum, hygro_time,
                 vmin, vmax, fps, step, output_file, location):
    """Vykreslí a uloží animaci do MP4."""

    has_sky2 = len(sky2_time) > 0
    frame_indices = list(range(0, len(sky1_data), step))
    n_frames = len(frame_indices)
    print(f"\nExport: {n_frames} snímků @ {fps} fps → {output_file}")
    video_s = n_frames / fps
    print(f"Délka videa: {video_s:.1f} s ({video_s/60:.1f} min)")

    # Šířka figury závisí na počtu senzorů
    figw = 14 if has_sky2 else 10
    fig, ax = plt.subplots(figsize=(figw, 6))
    fig.patch.set_facecolor("#111111")
    ax.set_facecolor("#111111")

    first = make_combined_frame(sky1_data, sky1_time, sky2_data, sky2_time, frame_indices[0])
    im = ax.imshow(first, cmap="inferno", vmin=vmin, vmax=vmax,
                   origin="lower", aspect="auto", interpolation="nearest")

    # Dělítko mezi senzory
    if has_sky2:
        ax.axvline(x=15.5, color="#666666", linewidth=0.8, linestyle="--")

    cbar = plt.colorbar(im, ax=ax, label="Teplota oblohy [°C]", fraction=0.03, pad=0.02)
    cbar.set_ticks(np.linspace(vmin, vmax, 8))
    cbar.ax.tick_params(labelsize=8)
    _add_colorbar_labels(cbar, vmin, vmax)

    xlabel = "Pixel (x)  [S1: 0–15 | S2: 16–31]" if has_sky2 else "Pixel (x)"
    ax.set_xlabel(xlabel, color="#aaaaaa", fontsize=9)
    ax.set_ylabel("Pixel (y)", color="#aaaaaa", fontsize=9)
    ax.tick_params(colors="#aaaaaa")
    for spine in ax.spines.values():
        spine.set_edgecolor("#444444")

    dt0 = datetime.fromtimestamp(sky1_time[frame_indices[0]] / 1e9, tz=timezone.utc)
    title_obj = ax.set_title(
        f"Sky Temperature — {location}\n{dt0.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        color="white", fontsize=11
    )

    hygro_text = ax.text(
        0.01, 0.97, "", transform=ax.transAxes,
        color="#88ff88", fontsize=9, va="top", ha="left",
        fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#00000088", edgecolor="none")
    )

    plt.tight_layout()

    def update(i):
        fi = frame_indices[i]
        ts_ns = sky1_time[fi]
        dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)

        combined = make_combined_frame(sky1_data, sky1_time, sky2_data, sky2_time, fi)
        im.set_data(combined)
        title_obj.set_text(
            f"Sky Temperature — {location}\n{dt.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )

        if hygro_time is not None and len(hygro_time) > 0:
            hi = min(int(np.searchsorted(hygro_time, ts_ns)), len(hygro_temp) - 1)
            hygro_text.set_text(f"Ta={hygro_temp[hi]:.1f}°C  RH={hygro_hum[hi]:.0f}%")
        else:
            hygro_text.set_text("")

        return [im, title_obj, hygro_text]

    anim = FuncAnimation(fig, update, frames=n_frames, interval=1000 / fps, blit=True)

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


# %% ── main ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    args = parse_args()

    (sky1_data, sky1_time, sky2_data, sky2_time,
     hygro_temp, hygro_hum, hygro_time) = load_hdf5_files(args.files)

    if args.preview:
        mid = len(sky1_data) // 2
        preview_frame(sky1_data, sky1_time, sky2_data, sky2_time,
                      mid, args.vmin, args.vmax, args.location)

    output_file = build_output_filename(args.files, args.out)

    export_video(
        sky1_data, sky1_time, sky2_data, sky2_time,
        hygro_temp, hygro_hum, hygro_time,
        vmin=args.vmin,
        vmax=args.vmax,
        fps=args.fps,
        step=args.step,
        output_file=output_file,
        location=args.location,
    )
