#!/bin/bash
# AMSKY01 Log Plotting Helper Script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/sensor_logs"

# Function to show usage
usage() {
    echo "Usage: $0 [options] [log_file]"
    echo ""
    echo "Options:"
    echo "  -l, --latest    Plot the latest log file"
    echo "  -a, --all       Plot all log files"
    echo "  -g, --gnuplot   Use gnuplot instead of matplotlib"
    echo "  -h, --help      Show this help"
    echo ""
    echo "If no log file is specified, plots the latest one."
    echo ""
    echo "Examples:"
    echo "  $0                                    # Plot latest log with matplotlib"
    echo "  $0 --gnuplot                         # Plot latest log with gnuplot"
    echo "  $0 sensor_logs/specific_file.csv     # Plot specific file"
    echo "  $0 --all                             # Plot all log files"
}

# Default settings
USE_GNUPLOT=false
PLOT_ALL=false
PLOT_LATEST=true

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -l|--latest)
            PLOT_LATEST=true
            shift
            ;;
        -a|--all)
            PLOT_ALL=true
            PLOT_LATEST=false
            shift
            ;;
        -g|--gnuplot)
            USE_GNUPLOT=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *.csv)
            LOG_FILE="$1"
            PLOT_LATEST=false
            shift
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Check if log directory exists
if [[ ! -d "$LOG_DIR" ]]; then
    echo "Error: Log directory $LOG_DIR not found"
    exit 1
fi

# Function to plot a single file
plot_file() {
    local file="$1"
    local filename=$(basename "$file")
    
    echo "Plotting: $filename"
    
    if [[ "$USE_GNUPLOT" == true ]]; then
        # Check if gnuplot is available
        if ! command -v gnuplot &> /dev/null; then
            echo "Error: gnuplot not found. Please install it or use matplotlib (remove -g flag)"
            exit 1
        fi
        gnuplot -c "$SCRIPT_DIR/plot_logs.gnuplot" "$file"
    else
        # Check if python and required modules are available
        if ! command -v python3 &> /dev/null; then
            echo "Error: python3 not found"
            exit 1
        fi
        
        # Activate virtual environment if it exists
        if [[ -f "$SCRIPT_DIR/venv/bin/activate" ]]; then
            source "$SCRIPT_DIR/venv/bin/activate"
        fi
        
        python3 "$SCRIPT_DIR/amsky_plot.py" "$file"
    fi
}

# Main logic
if [[ "$PLOT_ALL" == true ]]; then
    echo "Plotting all log files..."
    for file in "$LOG_DIR"/*.csv; do
        if [[ -f "$file" ]]; then
            plot_file "$file"
        fi
    done
elif [[ -n "$LOG_FILE" ]]; then
    # Plot specific file
    if [[ ! -f "$LOG_FILE" ]]; then
        echo "Error: File $LOG_FILE not found"
        exit 1
    fi
    plot_file "$LOG_FILE"
else
    # Plot latest file
    LATEST_FILE=$(ls -t "$LOG_DIR"/*.csv 2>/dev/null | head -n1)
    
    if [[ -z "$LATEST_FILE" ]]; then
        echo "Error: No CSV files found in $LOG_DIR"
        exit 1
    fi
    
    echo "Using latest log file: $(basename "$LATEST_FILE")"
    plot_file "$LATEST_FILE"
fi

echo "Done!"
