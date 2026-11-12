#!/bin/bash
# AMSKY systemd service installer/generator
# Automaticky detekuje cesty a generuje systemd service soubory
#
# Použití:
#   ./install.sh           # generuje a instaluje služby
#   ./install.sh --dry-run # pouze vygeneruje soubory bez instalace
#   ./install.sh --remove  # odstraní služby ze systemd

# ============================================================
# KONFIGURACE — uprav dle potřeby
#
# Hodnoty lze nastavit proměnnými prostředí nebo souborem systemd/.env
# (není ve verzovacím systému), např.:
#   DEVICE_NAME=AMSKY02_SVAKOV
#   SQM_ZP=11.976
#   SKYBRIGHTNESS_URL=https://skybrightness.com/api/v1/measurements
#   SKYBRIGHTNESS_TOKEN=...
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
    set +a
fi

# Název zařízení (použije se v názvech HDF5 souborů)
DEVICE_NAME="${DEVICE_NAME:-AMSKY02_SVAKOV}"

# Sériový port
SERIAL_PORT="${SERIAL_PORT:-/dev/ttyACM0}"

# Baudrate
BAUD_RATE="${BAUD_RATE:-115200}"

# Cesta pro ukládání logů (prázdné = ~/log/AMSKY)
LOG_PATH="${LOG_PATH:-}"

# Interval logování do HDF5 [s] (0 = bez omezení)
LOG_RATE="${LOG_RATE:-10}"

# SQM kalibrační konstanta (prázdné = výchozí hodnota vieweru)
SQM_ZP="${SQM_ZP:-}"

# HTTP JSON API loggeru (/data.json, čte ho např. amsky_tui.py); 0 = vypnuto
HTTP_PORT="${HTTP_PORT:-0}"

# Odesílání SQM na skybrightness.com (prázdná URL = vypnuto)
SKYBRIGHTNESS_URL="${SKYBRIGHTNESS_URL:-}"
SKYBRIGHTNESS_TOKEN="${SKYBRIGHTNESS_TOKEN:-}"
SKYBRIGHTNESS_INTERVAL="${SKYBRIGHTNESS_INTERVAL:-300}"
# Kanál TSL2591 (0/1), jehož SQM se odesílá
SKYBRIGHTNESS_CHANNEL="${SKYBRIGHTNESS_CHANNEL:-0}"

# rclone remote a cílová cesta pro upload
RCLONE_REMOTE="${RCLONE_REMOTE:-remote:/storage/meteo/svakov/AMSKY02}"

# Interval uploadu (systemd timer formát)
UPLOAD_INTERVAL="${UPLOAD_INTERVAL:-15min}"

# Minimální stáří souboru pro upload (aby se nenahrávaly otevřené soubory)
RCLONE_MIN_AGE="${RCLONE_MIN_AGE:-12m}"

# ============================================================
# AUTO-DETEKCE — neměnit pokud víš co děláš
# ============================================================

REPO_DIR="$(dirname "$SCRIPT_DIR")"
SW_DIR="$REPO_DIR/sw"
VENV_PYTHON="$REPO_DIR/venv/bin/python3"
CURRENT_USER="$(whoami)"
CURRENT_GROUP="$(id -gn)"
USER_HOME="$(eval echo "~$CURRENT_USER")"

if [[ -z "$LOG_PATH" ]]; then
    LOG_PATH="$USER_HOME/log/AMSKY"
fi

# Názvy unit souborů
LOGGER_UNIT="amsky-logger.service"
UPLOAD_UNIT="amsky-upload.service"
TIMER_UNIT="amsky-upload.timer"
# Token pro skybrightness se do unit souboru nezapisuje; čte se odtud
LOGGER_ENV="$SCRIPT_DIR/amsky-logger.env"

# ============================================================

print_config() {
    echo "=== AMSKY systemd installer ==="
    echo "Repo:         $REPO_DIR"
    echo "SW dir:       $SW_DIR"
    echo "Venv Python:  $VENV_PYTHON"
    echo "User:         $CURRENT_USER:$CURRENT_GROUP"
    echo "Device:       $DEVICE_NAME"
    echo "Port:         $SERIAL_PORT @ $BAUD_RATE"
    echo "Log path:     $LOG_PATH"
    echo "Log rate:     ${LOG_RATE}s"
    echo "SQM ZP:       ${SQM_ZP:-(výchozí)}"
    if [[ "$HTTP_PORT" != "0" ]]; then
        echo "HTTP API:     port $HTTP_PORT"
    fi
    if [[ -n "$SKYBRIGHTNESS_URL" ]]; then
        echo "Skybrightness: $SKYBRIGHTNESS_URL (interval ${SKYBRIGHTNESS_INTERVAL}s, light$SKYBRIGHTNESS_CHANNEL)"
    fi
    echo "rclone:       $RCLONE_REMOTE (interval $UPLOAD_INTERVAL, min-age $RCLONE_MIN_AGE)"
    echo ""
}

check_prerequisites() {
    if [[ ! -f "$VENV_PYTHON" ]]; then
        echo "VAROVÁNÍ: venv python nenalezen: $VENV_PYTHON"
        echo "         Použiji systémový python3"
        VENV_PYTHON="/usr/bin/python3"
    fi

    if [[ ! -f "$SW_DIR/amsky_viewer.py" ]]; then
        echo "CHYBA: amsky_viewer.py nenalezen v $SW_DIR" >&2
        return 1
    fi
}

# Přidá přepínač loggeru na nový řádek ExecStart (s pokračovacím "\").
add_arg() {
    extra_args+=" \\"$'\n'"    $1"
}

generate_services() {
    # Volitelné přepínače loggeru
    local extra_args=""
    local env_line=""
    if [[ -n "$SQM_ZP" ]]; then
        add_arg "--sqm-zp $SQM_ZP"
    fi
    if [[ "$HTTP_PORT" != "0" ]]; then
        add_arg "--api"
        add_arg "--http-port $HTTP_PORT"
    fi
    if [[ -n "$SKYBRIGHTNESS_URL" ]]; then
        if [[ -z "$SKYBRIGHTNESS_TOKEN" ]]; then
            echo "CHYBA: SKYBRIGHTNESS_URL je nastavena, ale chybí SKYBRIGHTNESS_TOKEN" >&2
            return 1
        fi
        add_arg "--upload-url $SKYBRIGHTNESS_URL"
        add_arg "--upload-interval $SKYBRIGHTNESS_INTERVAL"
        add_arg "--upload-channel $SKYBRIGHTNESS_CHANNEL"
        ( umask 077; echo "AMSKY_UPLOAD_TOKEN=$SKYBRIGHTNESS_TOKEN" > "$LOGGER_ENV" )
        env_line="EnvironmentFile=$LOGGER_ENV"
        echo "Vytvořen: $LOGGER_ENV (token, práva 600)"
    fi

    # --- Logger service ---
    cat > "$SCRIPT_DIR/$LOGGER_UNIT" <<EOF
[Unit]
Description=AMSKY Data Logger ($DEVICE_NAME)
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
Group=$CURRENT_GROUP
WorkingDirectory=$SW_DIR
Environment=HOME=$USER_HOME
$env_line
ExecStart=$VENV_PYTHON amsky_viewer.py \\
    --port $SERIAL_PORT \\
    --baud $BAUD_RATE \\
    --no-gui \\
    --verbose \\
    --log \\
    --log-name $DEVICE_NAME \\
    --log-path $LOG_PATH \\
    --log-rate $LOG_RATE$extra_args
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    echo "Vytvořen: $SCRIPT_DIR/$LOGGER_UNIT"

    # --- Upload service (oneshot) ---
    cat > "$SCRIPT_DIR/$UPLOAD_UNIT" <<EOF
[Unit]
Description=AMSKY Log Upload via rclone ($DEVICE_NAME)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$CURRENT_USER
Group=$CURRENT_GROUP
Environment=HOME=$USER_HOME
ExecStart=/usr/bin/rclone copy $LOG_PATH $RCLONE_REMOTE \\
    --min-age $RCLONE_MIN_AGE \\
    --log-level INFO
StandardOutput=journal
StandardError=journal
EOF
    echo "Vytvořen: $SCRIPT_DIR/$UPLOAD_UNIT"

    # --- Upload timer ---
    cat > "$SCRIPT_DIR/$TIMER_UNIT" <<EOF
[Unit]
Description=AMSKY periodický upload logů ($DEVICE_NAME)

[Timer]
OnBootSec=5min
OnUnitActiveSec=$UPLOAD_INTERVAL
Persistent=true

[Install]
WantedBy=timers.target
EOF
    echo "Vytvořen: $SCRIPT_DIR/$TIMER_UNIT"
}

install_services() {
    echo ""
    echo "Vytvářím adresář pro logy: $LOG_PATH"
    mkdir -p "$LOG_PATH"

    echo "Linkuji do systemd..."
    sudo systemctl link "$SCRIPT_DIR/$LOGGER_UNIT"
    sudo systemctl link "$SCRIPT_DIR/$UPLOAD_UNIT"
    sudo systemctl link "$SCRIPT_DIR/$TIMER_UNIT"
    sudo systemctl daemon-reload

    echo ""
    echo "=== Hotovo ==="
    echo ""
    echo "Pro spuštění loggeru:"
    echo "  sudo systemctl enable --now $LOGGER_UNIT"
    echo ""
    echo "Pro spuštění periodického uploadu:"
    echo "  sudo systemctl enable --now $TIMER_UNIT"
    echo ""
    echo "Kontrola stavu:"
    echo "  systemctl status $LOGGER_UNIT"
    echo "  systemctl list-timers $TIMER_UNIT"
    echo "  journalctl -u amsky-logger -f"
}

remove_services() {
    echo "Odstraňuji služby..."
    for unit in "$LOGGER_UNIT" "$TIMER_UNIT" "$UPLOAD_UNIT"; do
        sudo systemctl stop "$unit" 2>/dev/null || true
        sudo systemctl disable "$unit" 2>/dev/null || true
    done
    sudo systemctl daemon-reload
    echo "Hotovo. Vygenerované soubory v $SCRIPT_DIR zůstaly zachovány."
}

# ============================================================
# MAIN
# ============================================================

case "${1:-}" in
    --dry-run)
        print_config
        check_prerequisites || exit 1
        generate_services || exit 1
        echo ""
        echo "=== DRY RUN — soubory vygenerovány, ale neinstalováno ==="
        echo "Pro instalaci spusť:  $0"
        ;;
    --remove)
        remove_services
        ;;
    *)
        print_config
        check_prerequisites || exit 1
        generate_services || exit 1
        install_services
        ;;
esac
