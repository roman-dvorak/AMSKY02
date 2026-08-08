#!/usr/bin/env python3
"""
AMSKY01 Data Log Viewer - Interactive plotting with auto-refresh
Usage: amsky02-plot [options] [log_file1.csv] [log_file2.csv] ...
       amsky02-plot --interactive --refresh 30 --output myplot.png sensor_logs/latest.csv

Options:
  --interactive, -i     Show plot in interactive window
  --refresh, -r SECS    Auto-refresh interval in seconds (requires --interactive)
  --output, -o FILE     Output filename (default: amsky02_plots.png)
  --help, -h            Show this help
"""

import sys
import pandas as pd
from datetime import datetime
import numpy as np
import os
from pathlib import Path
import math
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import glob
from typing import List, Dict, Optional
import time
import threading
import argparse

def calculate_dew_point(temp_c, humidity_percent):
    """Calculate dew point using Magnus formula"""
    if pd.isna(temp_c) or pd.isna(humidity_percent):
        return np.nan
    
    a = 17.27
    b = 237.7
    
    alpha = ((a * temp_c) / (b + temp_c)) + math.log(humidity_percent / 100.0)
    dew_point = (b * alpha) / (a - alpha)
    
    return dew_point

def calculate_improved_light(adc_value, gain, exposure_time):
    """Calculate improved light measurement: ADC / gain × exposure_time"""
    if pd.isna(adc_value) or pd.isna(gain) or pd.isna(exposure_time) or gain == 0:
        return np.nan
    return adc_value / (gain * exposure_time)

class LogDataManager:
    """Manages CSV log files and data processing"""
    
    def __init__(self, log_directory="sensor_logs"):
        self.log_directory = Path(log_directory)
        self.csv_files = []
        self.current_data = None
        self.scan_files()
    
    def scan_files(self):
        """Scan for CSV files in the log directory"""
        if self.log_directory.exists():
            pattern = str(self.log_directory / "*.csv")
            self.csv_files = sorted(glob.glob(pattern), reverse=True)  # newest first
        else:
            self.csv_files = []
    
    def load_file(self, csv_file):
        """Load and process a single CSV file"""
        try:
            df = pd.read_csv(csv_file, sep=',', header=0)
            df['timestamp'] = pd.to_datetime(df['timestamp_utc'])
            
            # Calculate dew point
            df['dew_point'] = df.apply(
                lambda row: calculate_dew_point(row['hygro_temp'], row['hygro_humid']), 
                axis=1
            )
            
            # Calculate improved light measurements
            df['light_improved'] = df.apply(
                lambda row: calculate_improved_light(
                    row['light_raw'], row['light_gain'], row['light_integration']
                ), axis=1
            )
            df['light_ir_improved'] = df.apply(
                lambda row: calculate_improved_light(
                    row['light_ir'], row['light_gain'], row['light_integration']
                ), axis=1
            )
            
            self.current_data = df
            return True, f"Loaded {len(df)} data points"
        except Exception as e:
            return False, f"Error loading file: {str(e)}"
    
    def get_statistics(self):
        """Calculate statistics for current data"""
        if self.current_data is None or len(self.current_data) == 0:
            return {}
        
        df = self.current_data
        stats = {
            'total_points': len(df),
            'time_range': (df['timestamp'].min(), df['timestamp'].max()),
        }
        
        # Temperature stats
        temp_data = df['hygro_temp'].dropna()
        if not temp_data.empty:
            stats['temperature'] = {
                'min': temp_data.min(),
                'max': temp_data.max(),
                'mean': temp_data.mean(),
                'std': temp_data.std()
            }
        
        # Humidity stats
        humid_data = df['hygro_humid'].dropna()
        if not humid_data.empty:
            stats['humidity'] = {
                'min': humid_data.min(),
                'max': humid_data.max(),
                'mean': humid_data.mean(),
                'std': humid_data.std()
            }
        
        # Dew point stats
        dew_data = df['dew_point'].dropna()
        if not dew_data.empty:
            stats['dew_point'] = {
                'min': dew_data.min(),
                'max': dew_data.max(),
                'mean': dew_data.mean(),
                'std': dew_data.std()
            }
        
        # Light stats
        light_data = df['light_lux_calc'].dropna()
        if not light_data.empty:
            stats['light_lux'] = {
                'min': light_data.min(),
                'max': light_data.max(),
                'mean': light_data.mean(),
                'std': light_data.std()
            }
        
        # Improved light stats
        light_improved_data = df['light_improved'].dropna()
        if not light_improved_data.empty:
            stats['light_improved'] = {
                'min': light_improved_data.min(),
                'max': light_improved_data.max(),
                'mean': light_improved_data.mean(),
                'std': light_improved_data.std()
            }
        
        # Thermal stats
        thermal_columns = ['thermal_tl', 'thermal_tr', 'thermal_bl', 'thermal_br', 'thermal_center']
        for col in thermal_columns:
            if col in df.columns:
                thermal_data = df[col].dropna()
                if not thermal_data.empty:
                    stats[col] = {
                        'min': thermal_data.min(),
                        'max': thermal_data.max(),
                        'mean': thermal_data.mean(),
                        'std': thermal_data.std()
                    }
        
        return stats


def plot_amsky_data(csv_files):
    """Plot AMSKY01 sensor data in 3 subplots for multiple files"""
    
    dfs = []
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file, sep=',', header=0)
            df['timestamp'] = pd.to_datetime(df['timestamp_utc'])
            df['source_file'] = Path(csv_file).stem
            
            # Calculate dew point
            df['dew_point'] = df.apply(lambda row: calculate_dew_point(row['hygro_temp'], row['hygro_humid']), axis=1)
            
            # Calculate improved light measurements
            df['light_improved'] = df.apply(lambda row: calculate_improved_light(row['light_raw'], row['light_gain'], row['light_integration']), axis=1)
            df['light_ir_improved'] = df.apply(lambda row: calculate_improved_light(row['light_ir'], row['light_gain'], row['light_integration']), axis=1)
            
            dfs.append(df)
            print(f"Loaded {len(df)} data points from {csv_file}")
        except Exception as e:
            print(f"Error reading file {csv_file}: {e}")
            continue
    
    if not dfs:
        print("No valid data loaded.")
        return
    
    df = pd.concat(dfs).sort_values('timestamp').reset_index(drop=True)
    
    # Convert thermal data from K*100 to Celsius
    thermal_columns = ['thermal_tl', 'thermal_tr', 'thermal_bl', 'thermal_br', 'thermal_center']
    for col in thermal_columns:
        if col in df.columns:
            df[col + '_celsius'] = df[col] / 100.0 - 273.15
    
    # Calculate thermal difference: Thermal Center - Temperature
    df['thermal_diff'] = df['thermal_center_celsius'] - df['hygro_temp']
    
    # Ensure we have proper timestamp formatting
    
    # Create figure with 5 subplots
    fig, (ax1, ax2, ax3, ax4, ax5) = plt.subplots(5, 1, figsize=(12, 15), sharex=True)
    if len(csv_files) == 1:
        fig.suptitle(f'AMSKY01 Sensor Data - {Path(csv_files[0]).name}', fontsize=14)
    else:
        fig.suptitle(f'AMSKY01 Sensor Data - {len(csv_files)} files combined', fontsize=14)
    
    # Plot 1: Temperature, Humidity and Dew Point
    ax1_twin = ax1.twinx()
    
    # Filter data for hygro sensor (only rows with valid hygro data)
    hygro_data = df.dropna(subset=['hygro_temp', 'hygro_humid'])
    
    # Temperature and Dew Point on left axis
    line1 = ax1.plot(hygro_data['timestamp'], hygro_data['hygro_temp'], 'r-', linewidth=2, label='Temperature (°C)')
    line3 = ax1.plot(hygro_data['timestamp'], hygro_data['dew_point'], 'green', linewidth=2, alpha=0.7, label='Dew Point (°C)')
    ax1.set_ylabel('Temperature (°C)', color='red')
    ax1.tick_params(axis='y', labelcolor='red')
    ax1.grid(True, alpha=0.3)
    
    # Humidity on right axis
    line2 = ax1_twin.plot(hygro_data['timestamp'], hygro_data['hygro_humid'], 'b-', linewidth=2, label='Humidity (%)')
    ax1_twin.set_ylabel('Humidity (%)', color='blue')
    ax1_twin.tick_params(axis='y', labelcolor='blue')
    
    ax1.set_title('Temperature, Humidity and Dew Point')
    
    # Combined legend
    lines = line1 + line3 + line2
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc='upper left')
    
    # Plot 2: Light Sensor Data
    ax2_twin = ax2.twinx()
    
    # Filter data for light sensor (only rows with valid light data)
    light_data = df.dropna(subset=['light_raw', 'light_ir', 'light_gain', 'light_integration'])

    # Lux and Improved Light on left axis
    #line1 = ax2.semilogy(light_data['timestamp'], light_data['light_lux_calc'], 'orange', linewidth=2, label='Light (lux)', marker='o', markersize=2)
    line2 = ax2.semilogy(light_data['timestamp'], light_data['light_improved'], 'brown', linewidth=2, label='Improved Light (lux)', alpha=0.7)

    # Raw and IR on right axis
    line3 = ax2_twin.semilogy(light_data['timestamp'], light_data['light_raw'], 'grey', linewidth=1, label='Light Raw', alpha=0.7, linestyle='dotted')
    line4 = ax2_twin.semilogy(light_data['timestamp'], light_data['light_ir'], 'black', linewidth=1, label='Light IR', alpha=0.7, linestyle='dotted')

    ax2.set_ylabel('Light (lux)', color='orange')
    ax2.tick_params(axis='y', labelcolor='orange')
    ax2.set_title('Light Sensor Data')
    ax2.grid(True, alpha=0.3)

    ax2_twin.set_ylabel('Raw Values', color='grey')
    ax2_twin.tick_params(axis='y', labelcolor='grey')

    # Combined legend
    lines = line2 + line3 + line4
    labels = [l.get_label() for l in lines]
    ax2.legend(lines, labels, loc='upper left')
    
    # Plot 3: Thermal Sensor Data (in Celsius)
    thermal_celsius_columns = ['thermal_tl_celsius', 'thermal_tr_celsius', 'thermal_bl_celsius', 'thermal_br_celsius', 'thermal_center_celsius']
    thermal_labels = ['Thermal TL', 'Thermal TR', 'Thermal BL', 'Thermal BR', 'Thermal Center']
    colors = ['red', 'green', 'blue', 'magenta', 'black']
    linewidths = [1, 1, 1, 1, 2]
    
    # Filter data for thermal sensor (only rows with valid thermal data)
    thermal_data = df.dropna(subset=thermal_celsius_columns, how='all')  # At least one thermal column must be valid
    
    for col, label, color, lw in zip(thermal_celsius_columns, thermal_labels, colors, linewidths):
        if col in thermal_data.columns:
            # Plot only non-NaN values for this specific column
            col_data = thermal_data.dropna(subset=[col])
            if not col_data.empty:
                ax3.plot(col_data['timestamp'], col_data[col], color=color, linewidth=lw, label=label, alpha=0.8)
    
    ax3.set_ylabel('Temperature (°C)')
    ax3.set_title('Cloud Sensor Data (Celsius)')
    ax3.grid(True, alpha=0.3)
    ax3.legend()
    
    # Plot 4: Sensor Parameters (Gain and Integration Time)
    ax4_twin = ax4.twinx()
    
    # Use the same light sensor data as Plot 2
    
    # Gain on left axis
    line1 = ax4.plot(light_data['timestamp'], light_data['light_gain'], 'purple', linewidth=2, label='Gain', marker='s', markersize=3)
    ax4.set_ylabel('Gain', color='purple')
    ax4.tick_params(axis='y', labelcolor='purple')
    ax4.grid(True, alpha=0.3)
    
    # Integration time on right axis
    line2 = ax4_twin.plot(light_data['timestamp'], light_data['light_integration'], 'orange', linewidth=2, label='Integration Time (ms)', marker='o', markersize=3)
    ax4_twin.set_ylabel('Integration Time (ms)', color='orange')
    ax4_twin.tick_params(axis='y', labelcolor='orange')
    
    ax4.set_xlabel('UTC Time')
    ax4.set_title('Light Sensor Parameters')
    
    # Combined legend
    lines = line1 + line2
    labels = [l.get_label() for l in lines]
    ax4.legend(lines, labels, loc='upper left')
    
    # Plot 5: Thermal Difference (Thermal Center - Temperature)
    # Filter data where both thermal center and hygro temp are available
    diff_data = df.dropna(subset=['thermal_diff'])
    
    if not diff_data.empty:
        ax5.plot(diff_data['timestamp'], diff_data['thermal_diff'], 'purple', linewidth=2, label='Thermal Center - Air Temp', alpha=0.8)
        #ax5.axhline(y=0, color='black', linestyle='--', alpha=0.5, label='Zero difference')
        ax5.set_ylabel('Temperature Difference (°C)')
        ax5.set_title('Sky Temperature vs Air Temperature')
        ax5.grid(True, alpha=0.3)
        ax5.legend()
    
    ax5.set_xlabel('UTC Time')
    
    # Format x-axis as UTC time
    for ax in [ax1, ax2, ax3, ax4, ax5]:
        ax.xaxis_date()
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    # Save plot
    if len(csv_files) == 1:
        output_file = csv_files[0].replace('.csv', '_plots.png')
    else:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f'amsky02_combined_{timestamp}_plots.png'
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Plot saved as: {output_file}")
    
    # Show statistics
    print("\\nCombined Data Statistics:")
    print(f"Total data points: {len(df)}")
    print(f"Time range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    
    # Temperature stats (skip NaN values)
    temp_data = df['hygro_temp'].dropna()
    if not temp_data.empty:
        print(f"Temperature: {temp_data.min():.1f}°C to {temp_data.max():.1f}°C")
    
    # Humidity stats (skip NaN values)
    humid_data = df['hygro_humid'].dropna()
    if not humid_data.empty:
        print(f"Humidity: {humid_data.min():.1f}% to {humid_data.max():.1f}%")
    
    # Dew Point stats (skip NaN values)
    dew_data = df['dew_point'].dropna()
    if not dew_data.empty:
        print(f"Dew Point: {dew_data.min():.1f}°C to {dew_data.max():.1f}°C")
    
    # Light stats (skip NaN values)
    light_data = df['light_lux_calc'].dropna()
    if not light_data.empty:
        print(f"Light (calculated): {light_data.min():.6f} to {light_data.max():.6f} lux")
    
    # Improved Light stats (skip NaN values)
    light_improved_data = df['light_improved'].dropna()
    if not light_improved_data.empty:
        print(f"Light (improved): {light_improved_data.min():.6f} to {light_improved_data.max():.6f} units")

def plot_amsky_data_enhanced(csv_files, output_file="amsky02_plots.png", interactive=False, refresh_interval=None):
    """Enhanced plotting function with interactive display and auto-refresh"""
    
    def create_plot():
        """Create the plot with current data"""
        plt.clf()  # Clear the current figure
        
        dfs = []
        for csv_file in csv_files:
            try:
                df = pd.read_csv(csv_file, sep=',', header=0)
                df['timestamp'] = pd.to_datetime(df['timestamp_utc'])
                df['source_file'] = Path(csv_file).stem
                
                # Calculate dew point
                df['dew_point'] = df.apply(lambda row: calculate_dew_point(row['hygro_temp'], row['hygro_humid']), axis=1)
                
                # Calculate improved light measurements
                df['light_improved'] = df.apply(lambda row: calculate_improved_light(row['light_raw'], row['light_gain'], row['light_integration']), axis=1)
                df['light_ir_improved'] = df.apply(lambda row: calculate_improved_light(row['light_ir'], row['light_gain'], row['light_integration']), axis=1)
                
                dfs.append(df)
                if not interactive:  # Only print in non-interactive mode
                    print(f"Loaded {len(df)} data points from {csv_file}")
            except Exception as e:
                if not interactive:
                    print(f"Error reading file {csv_file}: {e}")
                continue
        
        if not dfs:
            if not interactive:
                print("No valid data loaded.")
            return None
        
        df = pd.concat(dfs).sort_values('timestamp').reset_index(drop=True)
        
        # Convert thermal data from K*100 to Celsius
        thermal_columns = ['thermal_tl', 'thermal_tr', 'thermal_bl', 'thermal_br', 'thermal_center']
        for col in thermal_columns:
            if col in df.columns:
                df[col + '_celsius'] = df[col] / 100.0 - 273.15
        
        # Calculate thermal difference: Thermal Center - Temperature
        df['thermal_diff'] = df['thermal_center_celsius'] - df['hygro_temp']
        
        # Create figure with 5 subplots
        fig, (ax1, ax2, ax3, ax4, ax5) = plt.subplots(5, 1, figsize=(12, 15), sharex=True)
        
        # Update title with current time if interactive
        if interactive:
            current_time = datetime.now().strftime('%H:%M:%S')
            if len(csv_files) == 1:
                fig.suptitle(f'AMSKY01 Sensor Data - {Path(csv_files[0]).name} (Updated: {current_time})', fontsize=14)
            else:
                fig.suptitle(f'AMSKY01 Sensor Data - {len(csv_files)} files combined (Updated: {current_time})', fontsize=14)
        else:
            if len(csv_files) == 1:
                fig.suptitle(f'AMSKY01 Sensor Data - {Path(csv_files[0]).name}', fontsize=14)
            else:
                fig.suptitle(f'AMSKY01 Sensor Data - {len(csv_files)} files combined', fontsize=14)
        
        # Plot 1: Temperature, Humidity and Dew Point
        ax1_twin = ax1.twinx()
        
        # Filter data for hygro sensor (only rows with valid hygro data)
        hygro_data = df.dropna(subset=['hygro_temp', 'hygro_humid'])
        
        # Temperature and Dew Point on left axis
        line1 = ax1.plot(hygro_data['timestamp'], hygro_data['hygro_temp'], 'r-', linewidth=2, label='Temperature (°C)')
        line3 = ax1.plot(hygro_data['timestamp'], hygro_data['dew_point'], 'green', linewidth=2, alpha=0.7, label='Dew Point (°C)')
        ax1.set_ylabel('Temperature (°C)', color='red')
        ax1.tick_params(axis='y', labelcolor='red')
        ax1.grid(True, alpha=0.3)
        
        # Humidity on right axis
        line2 = ax1_twin.plot(hygro_data['timestamp'], hygro_data['hygro_humid'], 'b-', linewidth=2, label='Humidity (%)')
        ax1_twin.set_ylabel('Humidity (%)', color='blue')
        ax1_twin.tick_params(axis='y', labelcolor='blue')
        
        ax1.set_title('Temperature, Humidity and Dew Point')
        
        # Combined legend
        lines = line1 + line3 + line2
        labels = [l.get_label() for l in lines]
        ax1.legend(lines, labels, loc='upper left')
        
        # Plot 2: Light Sensor Data
        ax2_twin = ax2.twinx()
        
        # Filter data for light sensor (only rows with valid light data)
        light_data = df.dropna(subset=['light_raw', 'light_ir', 'light_gain', 'light_integration'])

        # Lux and Improved Light on left axis
        line2 = ax2.semilogy(light_data['timestamp'], light_data['light_improved'], 'brown', linewidth=2, label='Improved Light (lux)', alpha=0.7)

        # Raw and IR on right axis
        line3 = ax2_twin.semilogy(light_data['timestamp'], light_data['light_raw'], 'grey', linewidth=1, label='Light Raw', alpha=0.7, linestyle='dotted')
        line4 = ax2_twin.semilogy(light_data['timestamp'], light_data['light_ir'], 'black', linewidth=1, label='Light IR', alpha=0.7, linestyle='dotted')

        ax2.set_ylabel('Light (lux)', color='orange')
        ax2.tick_params(axis='y', labelcolor='orange')
        ax2.set_title('Light Sensor Data')
        ax2.grid(True, alpha=0.3)

        ax2_twin.set_ylabel('Raw Values', color='grey')
        ax2_twin.tick_params(axis='y', labelcolor='grey')

        # Combined legend
        lines = line2 + line3 + line4
        labels = [l.get_label() for l in lines]
        ax2.legend(lines, labels, loc='upper left')
        
        # Plot 3: Thermal Sensor Data (in Celsius)
        thermal_celsius_columns = ['thermal_tl_celsius', 'thermal_tr_celsius', 'thermal_bl_celsius', 'thermal_br_celsius', 'thermal_center_celsius']
        thermal_labels = ['Thermal TL', 'Thermal TR', 'Thermal BL', 'Thermal BR', 'Thermal Center']
        colors = ['red', 'green', 'blue', 'magenta', 'black']
        linewidths = [1, 1, 1, 1, 2]
        
        # Filter data for thermal sensor (only rows with valid thermal data)
        thermal_data = df.dropna(subset=thermal_celsius_columns, how='all')  # At least one thermal column must be valid
        
        for col, label, color, lw in zip(thermal_celsius_columns, thermal_labels, colors, linewidths):
            if col in thermal_data.columns:
                # Plot only non-NaN values for this specific column
                col_data = thermal_data.dropna(subset=[col])
                if not col_data.empty:
                    ax3.plot(col_data['timestamp'], col_data[col], color=color, linewidth=lw, label=label, alpha=0.8)
        
        ax3.set_ylabel('Temperature (°C)')
        ax3.set_title('Cloud Sensor Data (Celsius)')
        ax3.grid(True, alpha=0.3)
        ax3.legend()
        
        # Plot 4: Sensor Parameters (Gain and Integration Time)
        ax4_twin = ax4.twinx()
        
        # Use the same light sensor data as Plot 2
        
        # Gain on left axis
        line1 = ax4.plot(light_data['timestamp'], light_data['light_gain'], 'purple', linewidth=2, label='Gain', marker='s', markersize=3)
        ax4.set_ylabel('Gain', color='purple')
        ax4.tick_params(axis='y', labelcolor='purple')
        ax4.grid(True, alpha=0.3)
        
        # Integration time on right axis
        line2 = ax4_twin.plot(light_data['timestamp'], light_data['light_integration'], 'orange', linewidth=2, label='Integration Time (ms)', marker='o', markersize=3)
        ax4_twin.set_ylabel('Integration Time (ms)', color='orange')
        ax4_twin.tick_params(axis='y', labelcolor='orange')
        
        ax4.set_xlabel('UTC Time')
        ax4.set_title('Light Sensor Parameters')
        
        # Combined legend
        lines = line1 + line2
        labels = [l.get_label() for l in lines]
        ax4.legend(lines, labels, loc='upper left')
        
        # Plot 5: Thermal Difference (Thermal Center - Temperature)
        # Filter data where both thermal center and hygro temp are available
        diff_data = df.dropna(subset=['thermal_diff'])
        
        if not diff_data.empty:
            ax5.plot(diff_data['timestamp'], diff_data['thermal_diff'], 'purple', linewidth=2, label='Thermal Center - Air Temp', alpha=0.8)
            #ax5.axhline(y=0, color='black', linestyle='--', alpha=0.5, label='Zero difference')
            ax5.set_ylabel('Temperature Difference (°C)')
            ax5.set_title('Sky Temperature vs Air Temperature')
            ax5.grid(True, alpha=0.3)
            ax5.legend()
        
        ax5.set_xlabel('UTC Time')
        
        # Format x-axis as UTC time
        for ax in [ax1, ax2, ax3, ax4, ax5]:
            ax.xaxis_date()
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        # Save plot with specified filename
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        if not interactive:
            print(f"Plot saved as: {output_file}")
        
        return df
    
    # Initial plot creation
    df = create_plot()
    if df is None:
        return
    
    # Show statistics (only in non-interactive mode or first time)
    if not interactive:
        print("\nCombined Data Statistics:")
        print(f"Total data points: {len(df)}")
        print(f"Time range: {df['timestamp'].min()} to {df['timestamp'].max()}")
        
        # Temperature stats (skip NaN values)
        temp_data = df['hygro_temp'].dropna()
        if not temp_data.empty:
            print(f"Temperature: {temp_data.min():.1f}°C to {temp_data.max():.1f}°C")
        
        # Humidity stats (skip NaN values)
        humid_data = df['hygro_humid'].dropna()
        if not humid_data.empty:
            print(f"Humidity: {humid_data.min():.1f}% to {humid_data.max():.1f}%")
        
        # Dew Point stats (skip NaN values)
        dew_data = df['dew_point'].dropna()
        if not dew_data.empty:
            print(f"Dew Point: {dew_data.min():.1f}°C to {dew_data.max():.1f}°C")
        
        # Light stats (skip NaN values)
        light_data = df['light_lux_calc'].dropna()
        if not light_data.empty:
            print(f"Light (calculated): {light_data.min():.6f} to {light_data.max():.6f} lux")
        
        # Improved Light stats (skip NaN values)
        light_improved_data = df['light_improved'].dropna()
        if not light_improved_data.empty:
            print(f"Light (improved): {light_improved_data.min():.6f} to {light_improved_data.max():.6f} units")
    
    if interactive:
        plt.ion()  # Turn on interactive mode
        plt.show()
        
        if refresh_interval:
            print(f"Interactive mode with auto-refresh every {refresh_interval} seconds. Press Ctrl+C to stop.")
            try:
                while True:
                    time.sleep(refresh_interval)
                    df = create_plot()
                    if df is not None:
                        plt.draw()
                        plt.pause(0.1)
            except KeyboardInterrupt:
                print("\nStopping auto-refresh.")
        else:
            print("Interactive mode. Close the plot window to exit.")
            plt.show(block=True)
        
        plt.ioff()  # Turn off interactive mode


def main():
    """Main entry point with argument parsing"""
    parser = argparse.ArgumentParser(
        description='AMSKY01 Data Log Viewer - Interactive plotting with auto-refresh',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  amsky02-plot data.csv                                    # Basic plot
  amsky02-plot --interactive data.csv                      # Interactive plot
  amsky02-plot -i -r 30 -o myplot.png data.csv            # Interactive with refresh
  amsky02-plot --output custom_name.png file1.csv file2.csv # Custom output name
        """
    )
    
    parser.add_argument('csv_files', nargs='+', 
                       help='CSV files to plot')
    parser.add_argument('-i', '--interactive', action='store_true',
                       help='Show plot in interactive window')
    parser.add_argument('-r', '--refresh', type=int, metavar='SECS',
                       help='Auto-refresh interval in seconds (requires --interactive)')
    parser.add_argument('-o', '--output', default='amsky02_plots.png',
                       help='Output filename (default: amsky02_plots.png)')
    
    # Handle case where no arguments are provided
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)
        
    args = parser.parse_args()
    
    # Validate arguments
    if args.refresh and not args.interactive:
        print("Error: --refresh requires --interactive mode")
        sys.exit(1)
        
    # Check if CSV files exist
    for csv_file in args.csv_files:
        if not os.path.exists(csv_file):
            print(f"Error: File {csv_file} not found")
            sys.exit(1)
    
    try:
        # Use enhanced plotting function
        plot_amsky_data_enhanced(
            csv_files=args.csv_files,
            output_file=args.output,
            interactive=args.interactive,
            refresh_interval=args.refresh
        )
    except Exception as e:
        print(f"Error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
