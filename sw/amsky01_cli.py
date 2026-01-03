#!/usr/bin/env python3
"""
AMSKY01 Sensor Data Viewer
Real-time visualization of sensor data with CLI interface
"""

import argparse
import serial
import socket
import threading
import time
import sys
from datetime import datetime, timezone, timedelta
import json
import math
import csv
import os


# CLI imports (optional)
try:
    import curses
    CLI_AVAILABLE = True
except ImportError:
    CLI_AVAILABLE = False
    print("Warning: curses not available.")


class SensorData:
    """Container for sensor data with thread-safe access"""
    def __init__(self):
        self.lock = threading.Lock()
        self.data_count = 0
        self.start_time = time.time()
        
        # Latest values for display
        self.latest = {
            'hygro': {'temp': None, 'humid': None, 'dew_point': None},
            'light': {'lux': None, 'raw': None, 'ir': None, 'gain': None, 'integration': None},
            'thermal': {'tl': None, 'tr': None, 'bl': None, 'br': None, 'center': None}
        }
        
    def add_data(self, sensor_type, data):
        """Add new sensor data point"""
        with self.lock:
            self.data_count += 1
            #print(f"[DEBUG SensorData] Adding {sensor_type} data: {data}")
            
            if sensor_type == 'hygro' and len(data) >= 2:
                try:
                    temp = float(data[0])
                    humid = float(data[1])
                    dew_point = self.calculate_dew_point(temp, humid)
                    self.latest['hygro'] = {'temp': temp, 'humid': humid, 'dew_point': dew_point}
                except ValueError:
                    pass
                    
            elif sensor_type == 'light' and len(data) >= 5:
                try:
                    lux = float(data[0])
                    raw = int(data[1])
                    ir = int(data[2])
                    gain = data[3]
                    integration = data[4]

                    # Calculate true lux using gain and integration
                    calculated_lux = self.calculate_true_lux(raw, gain, integration)
                    self.latest['light'] = {
                        'lux': calculated_lux, 'raw': raw, 'ir': ir, 
                        'gain': gain, 'integration': integration
                    }
                except ValueError:
                    pass
                    
            elif sensor_type == 'thermal' and len(data) >= 5:
                try:
                    tl = float(data[0])
                    tr = float(data[1])
                    bl = float(data[2])
                    br = float(data[3])
                    center = float(data[4])
                    
                    self.latest['thermal'] = {
                        'tl': tl, 'tr': tr, 'bl': bl, 'br': br, 'center': center
                    }
                except ValueError:
                    pass
                    
    def get_latest_data(self):
        """Get latest sensor values"""
        with self.lock:
            return self.latest.copy()
            
    def calculate_true_lux(self, raw, gain, integration):
        """Calculate true lux value based on gain and integration time"""
        try:
            # Safe conversion of integration time
            integration_time = float(integration) if integration != '0' else 100.0
            if integration_time == 0.0:
                integration_time = 100.0  # Default fallback
            
            integration_scale = 100.0 / integration_time
            
            # Handle different gain values based on TSL2591 settings
            gain_map = {
                '1': 1.0,      # 1x gain
                '25': 25.0,    # 25x gain  
                '428': 428.0,  # 428x gain
                '9876': 9876.0 # Max gain
            }
            gain_multiplier = gain_map.get(str(gain), 1.0)
            
            # Calculate lux with proper scaling
            # TSL2591 coefficient (approximate)
            lux = (raw * integration_scale) / gain_multiplier * 0.408
            
            return self.format_lux_value(lux)
            
        except (ValueError, ZeroDivisionError) as e:
            return "Error"
    
    def format_lux_value(self, lux):
        """Format lux value with appropriate units"""
        if lux >= 1e6:
            return f"{lux / 1e6:.3f} Mlux"
        elif lux >= 1e3:
            return f"{lux / 1e3:.3f} klux"
        elif lux >= 1.0:
            return f"{lux:.3f} lux"
        elif lux >= 1e-3:
            return f"{lux * 1e3:.3f} mlux"
        elif lux >= 1e-6:
            return f"{lux * 1e6:.3f} μlux"
        else:
            return f"{lux * 1e9:.3f} nlux"
    
    def calculate_dew_point(self, temp_c, humidity_percent):
        """Calculate dew point using Magnus formula"""
        try:
            if temp_c is None or humidity_percent is None:
                return None
            
            a = 17.27
            b = 237.7
            
            alpha = ((a * temp_c) / (b + temp_c)) + math.log(humidity_percent / 100.0)
            dew_point = (b * alpha) / (a - alpha)
            
            return dew_point
        except (ValueError, ZeroDivisionError, OverflowError):
            return None
    
    def get_stats(self):
        """Get session statistics"""
        with self.lock:
            uptime = time.time() - self.start_time
            return {
                'data_count': self.data_count,
                'uptime': uptime,
                'start_time': self.start_time
            }


class DataLogger:
    """CSV data logger with automatic file rotation every 10 minutes"""
    def __init__(self, sensor_data, log_dir="sensor_logs"):
        self.sensor_data = sensor_data
        self.log_dir = log_dir
        self.current_file = None
        self.current_writer = None
        self.current_file_handle = None
        self.data_buffer = []
        self.last_save_time = time.time()
        self.file_start_time = None
        self.next_rotation_time = None
        self.lock = threading.Lock()
        self.running = False
        self.logger_thread = None
        
        # Create log directory if it doesn't exist
        os.makedirs(self.log_dir, exist_ok=True)
        
        # CSV headers
        self.csv_headers = [
            'timestamp_utc', 'unix_timestamp',
            'hygro_temp', 'hygro_humid',
            'light_lux_calc', 'light_raw', 'light_ir', 'light_gain', 'light_integration',
            'thermal_tl', 'thermal_tr', 'thermal_bl', 'thermal_br', 'thermal_center'
        ]
        
    def start(self):
        """Start the data logger"""
        self.running = True
        self._create_new_file()
        
        # Calculate next 10-minute boundary for file rotation
        self._calculate_next_rotation_time()
        
        self.logger_thread = threading.Thread(target=self._logger_loop, daemon=True)
        self.logger_thread.start()
        print(f"Data logger started - logging to {self.log_dir}/")
        
    def stop(self):
        """Stop the data logger and save remaining data"""
        self.running = False
        if self.logger_thread:
            self.logger_thread.join(timeout=2.0)
        self._save_buffered_data(force=True)
        self._close_current_file()
        print("Data logger stopped")
        
    def log_data_point(self, sensor_type, data):
        """Log a single data point to buffer"""
        with self.lock:
            timestamp_utc = datetime.now(timezone.utc)
            unix_timestamp = timestamp_utc.timestamp()
            
            # Find or create entry for this timestamp (rounded to nearest second)
            timestamp_key = int(unix_timestamp)
            
            # Find existing entry or create new one
            entry = None
            for item in self.data_buffer:
                if int(item['unix_timestamp']) == timestamp_key:
                    entry = item
                    break
                    
            if entry is None:
                entry = {
                    'timestamp_utc': timestamp_utc.isoformat(),
                    'unix_timestamp': unix_timestamp,
                    'hygro_temp': None, 'hygro_humid': None,
                    'light_lux_calc': None, 'light_raw': None, 'light_ir': None, 
                    'light_gain': None, 'light_integration': None,
                    'thermal_tl': None, 'thermal_tr': None, 'thermal_bl': None, 
                    'thermal_br': None, 'thermal_center': None
                }
                self.data_buffer.append(entry)
                
            # Update entry with new sensor data
            try:
                if sensor_type == 'hygro' and len(data) >= 2:
                    entry['hygro_temp'] = float(data[0])
                    entry['hygro_humid'] = float(data[1])
                    
                elif sensor_type == 'light' and len(data) >= 5:
                    # For light sensor, we need to calculate lux properly
                    raw = int(data[1])
                    gain = data[3]
                    integration = data[4]
                    
                    # Calculate numerical lux value (not formatted string)
                    calculated_lux = self._calculate_numerical_lux(raw, gain, integration)
                    
                    entry['light_lux_calc'] = calculated_lux
                    entry['light_raw'] = raw
                    entry['light_ir'] = int(data[2])
                    entry['light_gain'] = gain
                    entry['light_integration'] = integration
                    
                elif sensor_type == 'thermal' and len(data) >= 5:
                    entry['thermal_tl'] = float(data[0])
                    entry['thermal_tr'] = float(data[1])
                    entry['thermal_bl'] = float(data[2])
                    entry['thermal_br'] = float(data[3])
                    entry['thermal_center'] = float(data[4])
                    
            except (ValueError, IndexError) as e:
                print(f"[DEBUG DataLogger] Error processing {sensor_type} data: {e}")
                
    def _calculate_numerical_lux(self, raw, gain, integration):
        """Calculate numerical lux value (not formatted string)"""
        try:
            integration_time = float(integration) if integration != '0' else 100.0
            if integration_time == 0.0:
                integration_time = 100.0
            
            integration_scale = 100.0 / integration_time
            
            gain_map = {
                '1': 1.0, '25': 25.0, '428': 428.0, '9876': 9876.0
            }
            gain_multiplier = gain_map.get(str(gain), 1.0)
            
            lux = (raw * integration_scale) / gain_multiplier * 0.408
            return lux
            
        except (ValueError, ZeroDivisionError):
            return None
            
    def _logger_loop(self):
        """Main logger loop - checks for data to save every 2 seconds"""
        while self.running:
            current_time = time.time()
            
            # Check if current time passed the next_rotation_time (UTC aligned)
            if self.next_rotation_time and current_time >= self.next_rotation_time:
                self._save_buffered_data(force=True)
                self._close_current_file()
                self._create_new_file()
                self._calculate_next_rotation_time()
                
            # Save data more frequently: every 10 seconds or if buffer gets large
            elif (current_time - self.last_save_time >= 10 or 
                  len(self.data_buffer) >= 50):
                self._save_buffered_data()
                
            # Force flush to disk every 2 minutes even if no new data
            elif (current_time - self.last_save_time >= 120):
                self._force_flush_file()
                
            time.sleep(2)  # Check every 2 seconds
            
    def _calculate_next_rotation_time(self):
        """Calculate next rotation time aligned to next 10-minute UTC boundary"""
        now = datetime.now(timezone.utc)
        
        # Calculate next 10-minute boundary
        current_minute = now.minute
        next_ten_minute = ((current_minute // 10) + 1) * 10
        
        if next_ten_minute >= 60:
            # Next boundary is in the next hour
            next_boundary = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            # Next boundary is in this hour
            next_boundary = now.replace(minute=next_ten_minute, second=0, microsecond=0)
        
        self.next_rotation_time = next_boundary.timestamp()
        
        print(f"[DataLogger] Next file rotation at: {next_boundary.strftime('%Y-%m-%d %H:%M:%S')} UTC")
            
    def _create_new_file(self):
        """Create a new CSV file with timestamp in year/month/day directory structure"""
        timestamp = datetime.now(timezone.utc)
        
        # Create year/month/day directory structure
        year_dir = os.path.join(self.log_dir, timestamp.strftime('%Y'))
        month_dir = os.path.join(year_dir, timestamp.strftime('%m'))
        day_dir = os.path.join(month_dir, timestamp.strftime('%d'))
        
        # Create directories if they don't exist
        os.makedirs(day_dir, exist_ok=True)
        
        filename = f"amsky01_data_{timestamp.strftime('%Y%m%d_%H%M%S')}_UTC.csv"
        filepath = os.path.join(day_dir, filename)
        
        try:
            self.current_file_handle = open(filepath, 'w', newline='', encoding='utf-8')
            self.current_writer = csv.DictWriter(self.current_file_handle, fieldnames=self.csv_headers)
            self.current_writer.writeheader()
            self.current_file_handle.flush()
            
            self.current_file = filepath
            self.file_start_time = time.time()
            print(f"[DataLogger] Created new log file: {filename}")
            
        except Exception as e:
            print(f"[DataLogger] Error creating file {filepath}: {e}")
            self.current_file_handle = None
            self.current_writer = None
            
    def _close_current_file(self):
        """Close current CSV file"""
        if self.current_file_handle:
            try:
                self.current_file_handle.close()
                print(f"[DataLogger] Closed log file: {os.path.basename(self.current_file)}")
            except Exception as e:
                print(f"[DataLogger] Error closing file: {e}")
            finally:
                self.current_file_handle = None
                self.current_writer = None
                self.current_file = None
                
    def _save_buffered_data(self, force=False):
        """Save buffered data to CSV file"""
        with self.lock:
            if not self.data_buffer or not self.current_writer:
                return
                
            try:
                # Sort buffer by timestamp before writing
                self.data_buffer.sort(key=lambda x: x['unix_timestamp'])
                
                # Write all buffered data
                for entry in self.data_buffer:
                    self.current_writer.writerow(entry)
                    
                self.current_file_handle.flush()
                
                entries_written = len(self.data_buffer)
                self.data_buffer.clear()
                self.last_save_time = time.time()
                
                if entries_written > 0:
                    print(f"[DataLogger] Saved {entries_written} entries to {os.path.basename(self.current_file)}")
                    
            except Exception as e:
                print(f"[DataLogger] Error saving data: {e}")


class SerialReader:
    """Data reader with connection handling"""
    def __init__(self, port, baudrate, sensor_data, data_logger=None):
        self.port = port
        self.baudrate = baudrate
        self.sensor_data = sensor_data
        self.data_logger = data_logger
        self.running = False
        self.thread = None
        self.serial_conn = None
        
    def start(self):
        """Start connection with error handling"""
        try:
            # Close any existing connection
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()
                time.sleep(0.5)
            
            # Create new serial connection with more robust settings
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1.0,          # Read timeout
                write_timeout=1.0,    # Write timeout
                xonxoff=False,        # Software flow control
                rtscts=False,         # Hardware flow control
                dsrdtr=False          # Hardware flow control
            )
            
            # Clear any existing data in buffers
            time.sleep(0.1)
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()
            
            # Verify connection
            if not self.serial_conn.is_open:
                raise serial.SerialException("Failed to open serial port")
                
            print(f"Serial port {self.port} opened successfully")
            
            self.running = True
            self.thread = threading.Thread(target=self._read_loop, daemon=True)
            self.thread.start()
            return True
            
        except Exception as e:
            print(f"Error opening serial port: {e}")
            if self.serial_conn:
                try:
                    self.serial_conn.close()
                except:
                    pass
                self.serial_conn = None
            return False
            
    def stop(self):
        """Stop connection"""
        self.running = False
        if self.serial_conn:
            self.serial_conn.close()
            
    def _read_loop(self):
        """Main data reading loop"""
        consecutive_errors = 0
        last_data_time = time.time()
        data_count = 0
        buffer = ""
        reconnect_attempts = 0
        max_reconnect_attempts = 5
        
        while self.running:
            try:
                if self.serial_conn and self.serial_conn.is_open:
                    # Check if data is available
                    bytes_waiting = self.serial_conn.in_waiting
                    if bytes_waiting > 0:
                        try:
                            # Read available data with timeout protection
                            chunk_size = min(bytes_waiting, 1024)
                            chunk_bytes = self.serial_conn.read(chunk_size)
                            
                            # Handle empty read (device disconnected or busy)
                            if not chunk_bytes:
                                consecutive_errors += 1
                                print(f"Empty read despite {bytes_waiting} bytes waiting - potential connection issue")
                                if consecutive_errors >= 3:
                                    print("Attempting to reconnect...")
                                    self._attempt_reconnect()
                                    consecutive_errors = 0
                                    reconnect_attempts += 1
                                    if reconnect_attempts >= max_reconnect_attempts:
                                        print(f"Max reconnect attempts ({max_reconnect_attempts}) reached, stopping")
                                        self.running = False
                                        break
                                time.sleep(0.1)
                                continue
                            
                            # Decode data
                            chunk = chunk_bytes.decode('utf-8', errors='ignore')
                            buffer += chunk
                            
                            # Process complete lines
                            while '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                line = line.strip()
                                
                                if line and ',' in line:
                                    parts = line.split(',')
                                    # Handle $ prefix in sensor type
                                    sensor_type_raw = parts[0]
                                    if sensor_type_raw.startswith('$'):
                                        sensor_type_raw = sensor_type_raw[1:]  # Remove $ prefix
                                    
                                    # Map cloud to thermal for compatibility
                                    if sensor_type_raw == 'cloud':
                                        sensor_type_raw = 'thermal'
                                    
                                    if len(parts) >= 2 and sensor_type_raw in ['hygro', 'light', 'thermal']:
                                        sensor_type = sensor_type_raw
                                        data = parts[1:]
                                        self.sensor_data.add_data(sensor_type, data)
                                        
                                        # Log to CSV if logger is available
                                        if self.data_logger:
                                            self.data_logger.log_data_point(sensor_type, data)
                                        
                                        consecutive_errors = 0  # Reset error counter on success
                                        reconnect_attempts = 0  # Reset reconnect counter on success
                                        data_count += 1
                                        last_data_time = time.time()
                                        print(f"[DEBUG SerialReader] [{data_count:04d}] {sensor_type}: {','.join(data)}")
                                    else:
                                        print(f"Invalid sensor type or format: {line} (sensor_type: {sensor_type_raw})")
                                elif line and len(line) > 3:
                                    print(f"Invalid data format: {line}")
                                    
                        except serial.SerialTimeoutException:
                            # Timeout is normal, just continue
                            pass
                        except Exception as read_error:
                            consecutive_errors += 1
                            print(f"Read operation error: {read_error}")
                            
                    else:
                        # No data available - check for timeout
                        if time.time() - last_data_time > 10.0:
                            print(f"No data received for 10 seconds, checking connection...")
                            last_data_time = time.time()
                            # Try to flush input buffer
                            try:
                                self.serial_conn.reset_input_buffer()
                            except:
                                pass
                    
                    time.sleep(0.05)  # Reasonable sleep to prevent CPU spinning
                else:
                    print("Serial connection closed")
                    break
                    
            except serial.SerialException as e:
                consecutive_errors += 1
                if self.running:
                    print(f"Serial error #{consecutive_errors}: {e}")
                    if consecutive_errors >= 3:
                        print("Attempting to reconnect due to serial errors...")
                        self._attempt_reconnect()
                        consecutive_errors = 0
                        reconnect_attempts += 1
                        if reconnect_attempts >= max_reconnect_attempts:
                            print(f"Max reconnect attempts ({max_reconnect_attempts}) reached, stopping reader")
                            self.running = False
                            break
                    time.sleep(0.5)
            except UnicodeDecodeError as e:
                print(f"Unicode decode error: {e} - clearing buffer and continuing...")
                buffer = ""  # Clear corrupted buffer
            except Exception as e:
                consecutive_errors += 1
                if self.running:
                    print(f"Unexpected error #{consecutive_errors}: {e}")
                    if consecutive_errors >= 5:
                        print(f"Too many unexpected errors ({consecutive_errors}), stopping reader")
                        self.running = False
                        break
                    time.sleep(0.1)
                    
    def _attempt_reconnect(self):
        """Attempt to reconnect"""
        try:
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()
            time.sleep(1)  # Wait before reconnecting
            
            self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=1)
            print(f"Successfully reconnected to {self.port}")
            return True
        except Exception as e:
            print(f"Reconnection failed: {e}")
            return False


class SimpleCLI:
    """Simple CLI interface without ncurses"""
    def __init__(self, sensor_data, serial_reader, data_logger=None):
        self.sensor_data = sensor_data
        self.serial_reader = serial_reader
        self.data_logger = data_logger
        self.running = True
        
    def run(self):
        """Run the simple CLI interface"""
        print("\nSimple CLI mode - Press Ctrl+C to quit")
        print("=" * 50)
        
        last_update = 0
        try:
            while self.running:
                current_time = time.time()
                
                # Update display every 2 seconds
                if current_time - last_update >= 2.0:
                    self._print_status()
                    last_update = current_time
                
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\nShutting down...")
            self.running = False
    
    def _print_status(self):
        """Print current sensor status"""
        with self.sensor_data.lock:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            print(f"\n[{timestamp}] Status Update:")
            print("-" * 30)
            
            # Hygro data
            hygro = self.sensor_data.latest['hygro']
            if hygro['temp'] is not None:
                temp = float(hygro['temp']) if isinstance(hygro['temp'], str) else hygro['temp']
                humid = float(hygro['humid']) if isinstance(hygro['humid'], str) else hygro['humid']
                print(f"Temperature: {temp:.1f}°C")
                print(f"Humidity: {humid:.1f}%")
                if hygro['dew_point'] is not None:
                    dew = float(hygro['dew_point']) if isinstance(hygro['dew_point'], str) else hygro['dew_point']
                    print(f"Dew Point: {dew:.1f}°C")
            else:
                print("Temperature: No data")
            
            # Light data
            light = self.sensor_data.latest['light']
            if light['lux'] is not None:
                print(f"Light: {light['lux']}")
            else:
                print("Light: No data")
            
            # Thermal data
            thermal = self.sensor_data.latest['thermal']
            if thermal['center'] is not None:
                center = float(thermal['center']) if isinstance(thermal['center'], str) else thermal['center']
                print(f"Thermal Center: {center:.1f}°C")
            else:
                print("Thermal: No data")
            
            # Stats
            runtime = time.time() - self.sensor_data.start_time
            data_rate = self.sensor_data.data_count / runtime if runtime > 0 else 0
            print(f"Runtime: {runtime:.0f}s, Data points: {self.sensor_data.data_count}, Rate: {data_rate:.1f}/s")
            
            if self.data_logger:
                print(f"Logging: {os.path.basename(self.data_logger.current_file) if self.data_logger.current_file else 'No file'}")

class CLIInterface:
    """ncurses-based CLI interface"""
    def __init__(self, sensor_data, serial_reader, data_logger=None):
        self.sensor_data = sensor_data
        self.serial_reader = serial_reader
        self.data_logger = data_logger
        self.stdscr = None
        
    def run(self):
        """Run the CLI interface"""
        curses.wrapper(self._main_loop)
        
    def _main_loop(self, stdscr):
        """Main curses loop"""
        self.stdscr = stdscr
        curses.curs_set(0)  # Hide cursor
        stdscr.nodelay(1)   # Non-blocking input
        stdscr.timeout(100) # Refresh every 100ms
        
        # Colors
        curses.start_color()
        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(4, curses.COLOR_CYAN, curses.COLOR_BLACK)
        
        while True:
            try:
                self._draw_screen()
                
                # Check for quit
                key = stdscr.getch()
                if key == ord('q') or key == ord('Q'):
                    break
                    
            except KeyboardInterrupt:
                break
                
    def _draw_screen(self):
        """Draw the main screen"""
        self.stdscr.clear()
        height, width = self.stdscr.getmaxyx()
        
        # Title
        title = "AMSKY01 Sensor Data Viewer"
        self.stdscr.addstr(0, (width - len(title)) // 2, title, curses.color_pair(4) | curses.A_BOLD)
        
        # Instructions
        self.stdscr.addstr(1, 2, "Press 'q' to quit", curses.color_pair(2))
        
        # Get latest data
        data = self.sensor_data.get_latest_data()
        
        # Draw boxes properly with consistent width
        box_width = 40
        
        # Hygro section (expand to include dew point)
        self._draw_box(3, 2, box_width, "HYGRO SENSOR", curses.color_pair(1))
        if data['hygro']['temp'] is not None:
            self.stdscr.addstr(4, 4, f"Temperature: {data['hygro']['temp']:7.2f} °C")
            self.stdscr.addstr(5, 4, f"Humidity:    {data['hygro']['humid']:7.2f} %")
            if data['hygro']['dew_point'] is not None:
                self.stdscr.addstr(6, 4, f"Dew Point:   {data['hygro']['dew_point']:7.2f} °C")
            else:
                self.stdscr.addstr(6, 4, "Dew Point:   ---.-- °C")
        else:
            self.stdscr.addstr(4, 4, "Temperature: ---.-- °C")
            self.stdscr.addstr(5, 4, "Humidity:    ---.-- %")
            self.stdscr.addstr(6, 4, "Dew Point:   ---.-- °C")
        
        # Light section (move down to avoid overlap)
        self._draw_box(8, 2, box_width, "LIGHT SENSOR", curses.color_pair(1))
        if data['light']['lux'] is not None:
            self.stdscr.addstr(9, 4,  f"Lux:         {str(data['light']['lux'])}")
            self.stdscr.addstr(10, 4,  f"Raw:         {data['light']['raw']:d}")
            self.stdscr.addstr(11, 4, f"IR:          {data['light']['ir']:d}")
            self.stdscr.addstr(12, 4, f"Gain:        {str(data['light']['gain'])}")
            self.stdscr.addstr(13, 4, f"Integration: {str(data['light']['integration'])} ms")
        else:
            self.stdscr.addstr(9, 4,  "Lux:         ----------")
            self.stdscr.addstr(10, 4,  "Raw:         ----------")
            self.stdscr.addstr(11, 4, "IR:          ----------")
            self.stdscr.addstr(12, 4, "Gain:        ----------")
            self.stdscr.addstr(13, 4, "Integration: ---------- ms")
        
        # Thermal section (move down to avoid overlap)
        self._draw_box(15, 2, box_width, "THERMAL SENSOR", curses.color_pair(1))
        if data['thermal']['tl'] is not None:
            self.stdscr.addstr(16, 4, f"Top-Left:     {data['thermal']['tl']:8.2f}")
            self.stdscr.addstr(17, 4, f"Top-Right:    {data['thermal']['tr']:8.2f}")
            self.stdscr.addstr(18, 4, f"Bottom-Left:  {data['thermal']['bl']:8.2f}")
            self.stdscr.addstr(19, 4, f"Bottom-Right: {data['thermal']['br']:8.2f}")
            self.stdscr.addstr(20, 4, f"Center:       {data['thermal']['center']:8.2f}")
        else:
            self.stdscr.addstr(16, 4, "Top-Left:     --------")
            self.stdscr.addstr(17, 4, "Top-Right:    --------")
            self.stdscr.addstr(18, 4, "Bottom-Left:  --------")
            self.stdscr.addstr(19, 4, "Bottom-Right: --------")
            self.stdscr.addstr(20, 4, "Center:       --------")
        
        # Status section (new box)
        self._draw_box(22, 2, box_width, "STATUS", curses.color_pair(4))
        
        # Connection status
        status_color = curses.color_pair(1) if self.serial_reader.running else curses.color_pair(3)
        status_text = "Connected" if self.serial_reader.running else "Disconnected"
        self.stdscr.addstr(23, 4, f"Connection: {status_text}", status_color)
        self.stdscr.addstr(24, 4, f"Port: {self.serial_reader.port}")
        
        # Session statistics
        stats = self.sensor_data.get_stats()
        uptime_str = self._format_uptime(stats.get('uptime', 0))
        self.stdscr.addstr(25, 4, f"Data points: {stats.get('data_count', 0)}")
        self.stdscr.addstr(26, 4, f"Session time: {uptime_str}")
        
        # Logging status
        if self.data_logger and self.data_logger.running:
            current_file = "" if not self.data_logger.current_file else os.path.basename(self.data_logger.current_file)
            self.stdscr.addstr(27, 4, f"Logging: ON", curses.color_pair(1))
            if current_file:
                # Truncate long filenames
                if len(current_file) > 30:
                    current_file = current_file[:27] + "..."
                self.stdscr.addstr(28, 4, f"File: {current_file}")
        else:
            self.stdscr.addstr(27, 4, f"Logging: OFF", curses.color_pair(3))
        
        # Current time
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        self.stdscr.addstr(0, width - len(current_time) - 2, current_time, curses.color_pair(2))
        
        self.stdscr.refresh()
    
    def _format_uptime(self, uptime_seconds):
        """Format uptime in human readable format"""
        if uptime_seconds < 60:
            return f"{int(uptime_seconds)}s"
        elif uptime_seconds < 3600:
            minutes = int(uptime_seconds // 60)
            seconds = int(uptime_seconds % 60)
            return f"{minutes}m {seconds}s"
        else:
            hours = int(uptime_seconds // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            return f"{hours}h {minutes}m"
    
    def _draw_box(self, y, x, width, title, color):
        """Draw a box with title"""
        # Top border with title
        title_text = f" {title} "
        border_length = width - len(title_text) - 2
        left_border = "─" * (border_length // 2)
        right_border = "─" * (border_length - border_length // 2)
        
        top_line = f"┌{left_border}{title_text}{right_border}┐"
        self.stdscr.addstr(y, x, top_line, color)
        
        # Side borders (height depends on content)
        if "HYGRO" in title:
            box_height = 4  # Added dew point
        elif "LIGHT" in title:
            box_height = 6
        elif "THERMAL" in title:
            box_height = 6
        elif "STATUS" in title:
            box_height = 7  # Status info
        else:
            box_height = 3
            
        for i in range(1, box_height):
            self.stdscr.addstr(y + i, x, "│", color)
            self.stdscr.addstr(y + i, x + width - 1, "│", color)
        
        # Bottom border
        bottom_line = "└" + "─" * (width - 2) + "┘"
        self.stdscr.addstr(y + box_height, x, bottom_line, color)





class TCPReader:
    """Data reader with connection handling"""
    def __init__(self, host, port, sensor_data, data_logger=None):
        self.host = host
        self.port = port
        self.sensor_data = sensor_data
        self.data_logger = data_logger
        self.running = False
        self.thread = None
        self.socket = None
        
    def start(self):
        """Start connection with error handling"""
        try:
            # Close existing connection
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                time.sleep(0.5)
            
            # Create TCP connection
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5.0)
            self.socket.connect((self.host, self.port))
            self.socket.settimeout(1.0)
            
            self.running = True
            self.thread = threading.Thread(target=self._read_loop, daemon=True)
            self.thread.start()
            return True
            
        except Exception as e:
            print(f"TCP connection error: {e}")
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
            return False
            
    def stop(self):
        """Stop connection"""
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            
    def _read_loop(self):
        """Main data reading loop"""
        consecutive_errors = 0
        last_data_time = time.time()
        data_count = 0
        buffer = ""
        reconnect_attempts = 0
        max_reconnect_attempts = 5
        
        while self.running:
            try:
                if self.socket:
                    try:
                        # Read data
                        chunk_bytes = self.socket.recv(1024)
                        
                        # Handle connection close
                        if not chunk_bytes:
                            consecutive_errors += 1
                            if consecutive_errors >= 3:
                                self._attempt_reconnect()
                                consecutive_errors = 0
                                reconnect_attempts += 1
                                if reconnect_attempts >= max_reconnect_attempts:
                                    self.running = False
                                    break
                            time.sleep(0.1)
                            continue
                        
                        # Decode received data
                        chunk = chunk_bytes.decode('utf-8', errors='ignore')
                        buffer += chunk
                        
                        # Process data lines
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.strip()
                            
                            if line and ',' in line:
                                parts = line.split(',')
                                # Remove $ prefix
                                sensor_type_raw = parts[0]
                                if sensor_type_raw.startswith('$'):
                                    sensor_type_raw = sensor_type_raw[1:]
                                
                                # Map cloud -> thermal
                                if sensor_type_raw == 'cloud':
                                    sensor_type_raw = 'thermal'
                                
                                if len(parts) >= 2 and sensor_type_raw in ['hygro', 'light', 'thermal']:
                                    sensor_type = sensor_type_raw
                                    data = parts[1:]
                                    self.sensor_data.add_data(sensor_type, data)
                                    
                                    # Log data if enabled
                                    if self.data_logger:
                                        self.data_logger.log_data_point(sensor_type, data)
                                    
                                    consecutive_errors = 0
                                    reconnect_attempts = 0
                                    data_count += 1
                                    last_data_time = time.time()
                                else:
                                    print(f"Invalid format: {line}")
                            elif line and len(line) > 3:
                                print(f"Bad data: {line}")
                                
                    except socket.timeout:
                        # Normal timeout
                        pass
                        
                    # Check for data timeout
                    if time.time() - last_data_time > 10.0:
                        print("No data for 10s, checking connection")
                        last_data_time = time.time()
                    
                    time.sleep(0.05)  # Prevent CPU spinning
                else:
                    print("TCP connection lost")
                    break
                    
            except socket.error:
                consecutive_errors += 1
                if self.running:
                    if consecutive_errors >= 3:
                        self._attempt_reconnect()
                        consecutive_errors = 0
                        reconnect_attempts += 1
                        if reconnect_attempts >= max_reconnect_attempts:
                            self.running = False
                            break
                    time.sleep(0.5)
            except UnicodeDecodeError:
                buffer = ""  # Clear corrupted buffer
            except Exception:
                consecutive_errors += 1
                if self.running:
                    if consecutive_errors >= 5:
                        self.running = False
                        break
                    time.sleep(0.1)
                    
    def _attempt_reconnect(self):
        """Attempt to reconnect"""
        try:
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
            time.sleep(1)  # Wait before reconnect
            
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5.0)
            self.socket.connect((self.host, self.port))
            self.socket.settimeout(1.0)
        except Exception:
            self.socket = None


def list_serial_ports():
    """List available serial ports"""
    try:
        import serial.tools.list_ports as list_ports
        ports = list_ports.comports()
        available_ports = []
        
        print("\nAvailable serial ports:")
        for port in ports:
            print(f"  {port.device} - {port.description}")
            available_ports.append(port.device)
        
        if not available_ports:
            print("  No serial ports found")
        
        return available_ports
    except ImportError:
        print("Error: serial.tools.list_ports not available")
        return []


def main():
    """Application entry point"""
    parser = argparse.ArgumentParser(description='AMSKY01 Sensor Data Viewer')
    parser.add_argument('--port', '-p', default='/dev/ttyACM0', 
                        help='Serial port (default: /dev/ttyACM0)')
    parser.add_argument('--baudrate', '-b', type=int, default=115200,
                        help='Serial baudrate (default: 115200)')
    parser.add_argument('--tcp', type=int, metavar='PORT',
                        help='TCP port (uses localhost, replaces serial)')
    parser.add_argument('--host', default='localhost',
                        help='TCP host (default: localhost)')
    parser.add_argument('--log', action='store_true',
                        help='Enable CSV logging')
    parser.add_argument('--list-ports', '-l', action='store_true',
                        help='List serial ports and exit')
    parser.add_argument('--no-tui', action='store_true',
                        help='Disable ncurses TUI, use simple CLI output')
    
    args = parser.parse_args()
    
    # List ports if requested
    if args.list_ports:
        list_serial_ports()
        sys.exit(0)
    
    # Check CLI availability (only needed for ncurses TUI)
    if not args.no_tui and not CLI_AVAILABLE:
        print("Error: curses not available. Use --no-tui for simple CLI interface.")
        sys.exit(1)
    
    # List available ports for information
    available_ports = list_serial_ports()
    if args.port not in available_ports and available_ports:
        print(f"\nWarning: Selected port {args.port} not found in available ports.")
        print("Continuing anyway - device might not be connected yet.")
    
    # Create data container
    sensor_data = SensorData()
    
    # Create data logger if requested
    data_logger = None
    if args.log:
        data_logger = DataLogger(sensor_data)
        data_logger.start()
    
    # Create appropriate reader
    if args.tcp:
        reader = TCPReader(args.host, args.tcp, sensor_data, data_logger)
        if not reader.start():
            print(f"Failed to connect to TCP server at {args.host}:{args.tcp}")
            sys.exit(1)
        print(f"Connected to TCP server at {args.host}:{args.tcp}")
    else:
        reader = SerialReader(args.port, args.baudrate, sensor_data, data_logger)
        if not reader.start():
            print(f"Failed to open serial port {args.port}")
            print("Try using --list-ports to see available ports")
            sys.exit(1)
        print(f"Connected to {args.port} at {args.baudrate} baud")
    
    # Check if we should use simple CLI or ncurses
    # Check if we should use simple CLI or ncurses
    try:
        if args.no_tui:
            # Use simple CLI without ncurses
            print("Starting simple CLI interface...")
            app = SimpleCLI(sensor_data, reader, data_logger)
            app.run()
        else:
            # Use ncurses TUI (default)
            print("Starting CLI interface...")
            app = CLIInterface(sensor_data, reader, data_logger)
            app.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        reader.stop()
        
        # Stop data logger and save final data (if enabled)
        if data_logger:
            data_logger.stop()
        
        print("Goodbye!")

if __name__ == '__main__':
    main()
