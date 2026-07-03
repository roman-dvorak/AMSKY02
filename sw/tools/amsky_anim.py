# %%%
import h5py
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, FFMpegWriter
from datetime import datetime
from tqdm import tqdm
import pandas as pd

# Nastavení černého pozadí
plt.style.use('dark_background')

# Načtení všech HDF souborů z daného dne
import glob
import os

data_dir = "../../doc/data"
target_date = "20260103"  # Datum ve formátu YYYYMMDD

# Najdeme všechny soubory daného dne
hdf_files = sorted(glob.glob(f"{data_dir}/AMSKY01_{target_date}_*.h5"))
hdf_files = sorted(glob.glob(f"{data_dir}/AMSKY01_{target_date}_22.h5"))
print(f"=== Nalezené soubory ({len(hdf_files)}) ===")
for f in hdf_files:
    print(f"  {os.path.basename(f)}")

# Načtení a spojení dat ze všech souborů
hygro_hum_list = []
hygro_temp_list = []
hygro_time_list = []
light_all_list = []
light_time_list = []
sky_temp_list = []
sky_data_list = []
sky_time_list = []

print("\n=== Načítám soubory ===")
for hdf_file in hdf_files:
    print(f"  {os.path.basename(hdf_file)}")
    with h5py.File(hdf_file, 'r') as f:
        hygro_hum_list.append(f['hygro']['hum'][:])
        hygro_temp_list.append(f['hygro']['temp'][:])
        hygro_time_list.append(f['hygro']['time'][:])
        
        light_all_list.append(f['light']['all'][:])
        light_time_list.append(f['light']['time'][:])
        
        sky_temp_list.append(f['sky']['temp'][:])
        sky_data_list.append(f['sky']['data'][:])
        sky_time_list.append(f['sky']['time'][:])

# Spojení všech dat
hygro_hum = np.concatenate(hygro_hum_list)
hygro_temp = np.concatenate(hygro_temp_list)
hygro_time = np.concatenate(hygro_time_list)

light_all = np.concatenate(light_all_list)
light_time = np.concatenate(light_time_list)

sky_temp = np.concatenate(sky_temp_list)
sky_data = np.concatenate(sky_data_list, axis=0)
sky_time = np.concatenate(sky_time_list)

print(f"\n=== Celkem načteno ===")
print(f"  hygro/hum: {hygro_hum.shape}")
print(f"  hygro/temp: {hygro_temp.shape}")
print(f"  light/all: {light_all.shape}")
print(f"  sky/temp: {sky_temp.shape}")
print(f"  sky/data: {sky_data.shape}")

# Převod unix timestamp (nanosekundy) na datetime
hygro_datetime = pd.to_datetime(hygro_time, unit='ns')
light_datetime = pd.to_datetime(light_time, unit='ns')
sky_datetime = pd.to_datetime(sky_time, unit='ns')

print(f"\n=== Časové rozsahy ===")
print(f"  hygro: {hygro_datetime[0]} - {hygro_datetime[-1]}")
print(f"  light: {light_datetime[0]} - {light_datetime[-1]}")
print(f"  sky: {sky_datetime[0]} - {sky_datetime[-1]}")

# %%
# Grafy hygro, temp, light
fig, axes = plt.subplots(3, 1, figsize=(12, 8))
fig.suptitle('AMSKY01 Environmental Data')

axes[0].plot(hygro_datetime, hygro_temp)
axes[0].set_ylabel('Temperature [°C]')
axes[0].grid(True)

axes[1].plot(hygro_datetime, hygro_hum)
axes[1].set_ylabel('Humidity [%]')
axes[1].grid(True)

axes[2].plot(light_datetime, light_all)
axes[2].set_ylabel('Light')
axes[2].set_xlabel('Time')
axes[2].grid(True)

plt.tight_layout()
plt.show()

# %%
# Ukázka jednoho snímku sky/data
fig, ax = plt.subplots(figsize=(14, 9))
vmin = -30
vmax = 5

# Vykreslíme prostřední snímek
mid_frame = len(sky_data) // 2
im = ax.imshow(sky_data[mid_frame], cmap='hot', vmin=vmin, vmax=vmax, origin='lower', aspect='auto')
cbar = plt.colorbar(im, ax=ax, label='Sky temp [°C]')
# Přidání popisek ke colorbar
cbar.ax.text(1.5, 0, 'Cloudy', rotation=0, va='center', ha='left', fontsize=10, color='white')
cbar.ax.text(1.5, -20, 'Clear', rotation=0, va='center', ha='left', fontsize=10, color='white')
datetime_label = sky_datetime[0].strftime('%Y-%m-%d %H:%M:%S %Z')
title = ax.set_title(f'Sky Temperature - AMSKY01 - Sutiny Barbecue\n{datetime_label}')#ax.set_xlabel('Width (16 pixels)')
#ax.set_ylabel('Height (12 pixels)')
plt.tight_layout()
plt.show()

# %%
# Animace sky/data
fig, ax = plt.subplots(figsize=(14, 9))

# sky_data má tvar (time, height, width) = (1798, 12, 16)
vmin = -30
vmax = 5

im = ax.imshow(sky_data[0], cmap='hot', vmin=vmin, vmax=vmax, origin='lower', aspect='auto')
cbar = plt.colorbar(im, ax=ax, label='Sky temp [°C]')
# Přidání popisek ke colorbar
cbar.ax.text(1.5, 0, 'Cloudy', rotation=0, va='center', ha='left', fontsize=10, color='white')
cbar.ax.text(1.5, -20, 'Clear', rotation=0, va='center', ha='left', fontsize=10, color='white')
datetime_label = sky_datetime[0].strftime('%Y-%m-%d %H:%M:%S %Z')
title = ax.set_title(f'Sky Temperature - AMSKY01 - Sutiny Barbecue\n{datetime_label}')
# ax.set_xlabel('Width')
# ax.set_ylabel('Height')
plt.tight_layout()
# Použijeme každý druhý snímek
frame_indices = range(0, len(sky_data), 2)

def update(idx):
    frame1 = frame_indices[idx]
    frame2 = frame_indices[min(idx + 1, len(frame_indices) - 1)]
    frame = (frame1 + frame2) // 2
    im.set_data(sky_data[frame])
    datetime_label = sky_datetime[frame].strftime('%Y-%m-%d %H:%M:%S %Z')
    title = ax.set_title(f'Sky Temperature - AMSKY01 - Sutiny Barbecue\n{datetime_label}')
    return [im, title]

anim = FuncAnimation(fig, update, frames=len(frame_indices), interval=100, blit=True)

# Uložení animace jako MP4 s progress barem
output_file = f'sky_temp_animation_{target_date}_22.mp4'
writer = FFMpegWriter(fps=20, metadata=dict(artist='AMSKY01'), bitrate=1800)

print(f"Ukládám animaci do {output_file}...")
with tqdm(total=len(frame_indices), desc="Rendering frames") as pbar:
    def progress_callback(current_frame, total_frames):
        pbar.update(1)
    
    anim.save(output_file, writer=writer, progress_callback=progress_callback)

print(f'Animace uložena do {output_file}')
plt.show()

# %%
