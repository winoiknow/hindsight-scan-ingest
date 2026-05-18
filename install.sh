#!/usr/bin/env bash
# hindsight-scan-ingest installer
set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m';  GRN='\033[0;32m';  YLW='\033[1;33m'
CYN='\033[0;36m';  BLU='\033[0;34m';  MAG='\033[0;35m'
WHT='\033[1;37m';  BOLD='\033[1m';    DIM='\033[2m';  RST='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────
info()    { echo -e "  ${CYN}»${RST}  $*"; }
success() { echo -e "  ${GRN}✔${RST}  $*"; }
warn()    { echo -e "  ${YLW}⚠${RST}  $*"; }
error()   { echo -e "  ${RED}✖${RST}  $*" >&2; exit 1; }
section() { echo -e "\n${BOLD}${BLU}━━  $*  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"; }

ask() {
  local prompt="$1" default="$2" var_name="$3"
  local answer
  echo -en "  ${WHT}${prompt}${RST} ${DIM}[${default}]${RST}: "
  read -r answer
  printf -v "$var_name" '%s' "${answer:-$default}"
}

ask_yn() {
  local prompt="$1" default="$2"
  local answer
  echo -en "  ${WHT}${prompt}${RST} ${DIM}(y/n) [${default}]${RST}: "
  read -r answer
  answer="${answer:-$default}"
  [[ "$answer" =~ ^[Yy]$ ]]
}

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Banner ─────────────────────────────────────────────────────────────────────
clear
echo -e "${CYN}${BOLD}"
cat <<'BANNER'

   ╔════════════════════════════════════════════════════════════════╗
   ║                                                                ║
   ║   ██╗  ██╗██╗███╗  ██╗██████╗ ███████╗██╗████████╗███████╗   ║
   ║   ██║  ██║██║████╗ ██║██╔══██╗██╔════╝██║╚══██╔══╝██╔════╝   ║
   ║   ███████║██║██╔██╗██║██║  ██║███████╗██║   ██║   █████╗     ║
   ║   ██╔══██║██║██║╚████║██║  ██║╚════██║██║   ██║   ██╔══╝     ║
   ║   ██║  ██║██║██║ ╚███║██████╔╝███████║██║   ██║   ███████╗   ║
   ║   ╚═╝  ╚═╝╚═╝╚═╝  ╚══╝╚═════╝ ╚══════╝╚═╝   ╚═╝   ╚══════╝   ║
   ║                                                                ║
   ║          ·  S C A N   I N G E S T  ·  I N S T A L L  ·       ║
   ║                                                                ║
   ║      Document ingestion daemon  ·  Vectorize Hindsight         ║
   ╚════════════════════════════════════════════════════════════════╝

BANNER
echo -e "${RST}"
echo -e "  ${DIM}Working directory: ${INSTALL_DIR}${RST}"
echo ""

# ── Step 1 — Python preflight ─────────────────────────────────────────────────
section "Step 1  Python preflight"

PY=""
for candidate in python3.12 python3.11 python3; do
  if command -v "$candidate" &>/dev/null; then
    PY="$candidate"; break
  fi
done
[[ -n "$PY" ]] || error "Python 3.11+ not found. Install it and re-run."

PY_VER=$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=${PY_VER%%.*}
PY_MINOR=${PY_VER##*.}

if [[ "$PY_MAJOR" -lt 3 || ( "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 11 ) ]]; then
  error "Python $PY_VER found, but 3.11+ is required."
fi
success "Python $PY_VER  ($PY)"

# Prefer local venv if possible, fall back to --break-system-packages
VENV_DIR="${INSTALL_DIR}/.venv"
if "$PY" -m venv --help &>/dev/null 2>&1; then
  if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment…"
    "$PY" -m venv "$VENV_DIR" && success "Virtual environment created at .venv"
  else
    success "Virtual environment already exists at .venv"
  fi
  PIP="${VENV_DIR}/bin/pip"
  PY_RUN="${VENV_DIR}/bin/python"
else
  warn "venv module unavailable — will install to user site-packages."
  PIP="$PY -m pip"
  PY_RUN="$PY"
fi

# ── Step 2 — Install dependencies ─────────────────────────────────────────────
section "Step 2  Install dependencies"

info "Installing Python packages from requirements.txt…"
if [[ -d "$VENV_DIR" ]]; then
  "${VENV_DIR}/bin/pip" install -q -r "${INSTALL_DIR}/requirements.txt" \
    && success "Packages installed"
else
  "$PY" -m pip install -q --user -r "${INSTALL_DIR}/requirements.txt" \
    && success "Packages installed (user site)"
fi

# Optional: Tesseract
if command -v tesseract &>/dev/null; then
  TESS_VER=$(tesseract --version 2>&1 | head -1)
  success "Tesseract detected: ${TESS_VER}"
else
  warn "Tesseract not found — image OCR fallback will be disabled."
  warn "Install with:  sudo apt install tesseract-ocr   (Ubuntu/Debian)"
  warn "               brew install tesseract             (macOS)"
fi

# ── Step 3 — Configuration wizard ─────────────────────────────────────────────
section "Step 3  Configuration"

echo ""
echo -e "  ${DIM}Press Enter to accept the default shown in [brackets].${RST}"
echo ""

# Server
ask "Hindsight server URL" "http://localhost:8888" CFG_SERVER_URL
ask "API key (leave blank for local Docker)" "" CFG_API_KEY

echo ""
# Memory routing — list existing banks before asking
echo -e "  ${DIM}── Memory routing ─────────────────────────────────────────────${RST}"
echo -e "  ${DIM}Tip: bank_id must match what your agent is configured to read.${RST}"
echo ""
echo -e "  ${CYN}»${RST}  Fetching available banks from ${CFG_SERVER_URL}…"
BANKS_JSON=$(curl -sf --max-time 5 "${CFG_SERVER_URL}/v1/default/banks" 2>/dev/null || true)
if [[ -n "$BANKS_JSON" ]]; then
  BANK_LIST=$(echo "$BANKS_JSON" | python3 -c "
import json, sys
data = json.load(sys.stdin)
banks = data.get('banks', data if isinstance(data, list) else [])
for b in banks:
    bid = b.get('bank_id', b.get('id', '?'))
    print(f'     • {bid}')
" 2>/dev/null)
  if [[ -n "$BANK_LIST" ]]; then
    echo -e "  ${GRN}✔${RST}  Existing banks:"
    echo "$BANK_LIST"
  else
    echo -e "  ${DIM}     (no banks yet — one will be created on first ingest)${RST}"
  fi
else
  warn "Cannot reach ${CFG_SERVER_URL} — enter bank_id manually."
fi
echo ""
ask "Bank ID" "documents" CFG_BANK_ID
ask "Source label (context tag for fact extraction)" "document-ingest" CFG_SOURCE
ask "Session tag (optional, stored in memory metadata)" "" CFG_SESSION

echo ""
# Folders
echo -e "  ${DIM}── Watched folders ────────────────────────────────────────────${RST}"
echo -e "  ${DIM}Enter one folder path per prompt. Leave blank to finish.${RST}"
echo ""
CFG_FOLDERS=()
while true; do
  FOLDER_PROMPT="Folder path"
  [[ ${#CFG_FOLDERS[@]} -gt 0 ]] && FOLDER_PROMPT="Another folder (blank to finish)"
  echo -en "  ${WHT}${FOLDER_PROMPT}${RST}: "
  read -r folder_input
  [[ -z "$folder_input" ]] && break
  if [[ ! -d "$folder_input" ]]; then
    warn "Directory does not exist yet: ${folder_input}  (will be created or you can add it later)"
  fi
  CFG_FOLDERS+=("$folder_input")
done
[[ ${#CFG_FOLDERS[@]} -eq 0 ]] && CFG_FOLDERS=("/path/to/your/docs")

echo ""
# Interval + chunking
echo -e "  ${DIM}── Scanning ───────────────────────────────────────────────────${RST}"
ask "Scan interval (minutes)" "15" CFG_INTERVAL
ask "Enable local chunking? (y/n)" "n" CFG_CHUNK_RAW
CFG_CHUNKING="false"
if [[ "$CFG_CHUNK_RAW" =~ ^[Yy]$ ]]; then
  CFG_CHUNKING="true"
  ask "Chunk size (tokens/words)" "1000" CFG_CHUNK_SIZE
  ask "Chunk overlap (tokens/words)" "100" CFG_OVERLAP
else
  CFG_CHUNK_SIZE="1000"
  CFG_OVERLAP="100"
fi

# ── Step 4 — Write config.yaml ────────────────────────────────────────────────
section "Step 4  Writing config.yaml"

CONFIG_PATH="${INSTALL_DIR}/config.yaml"

# Build folders YAML block
FOLDERS_YAML=""
for f in "${CFG_FOLDERS[@]}"; do
  FOLDERS_YAML="${FOLDERS_YAML}  - ${f}"$'\n'
done

cat > "$CONFIG_PATH" <<EOF
# ── Hindsight connection ──────────────────────────────────────────────────────
server_url: ${CFG_SERVER_URL}
api_key: "${CFG_API_KEY}"

# ── Memory routing ────────────────────────────────────────────────────────────
bank_id: "${CFG_BANK_ID}"
source: "${CFG_SOURCE}"
session: "${CFG_SESSION}"

# ── Folders to watch ──────────────────────────────────────────────────────────
folders:
${FOLDERS_YAML}
# ── Scan interval (minutes) ───────────────────────────────────────────────────
scan_interval_minutes: ${CFG_INTERVAL}

# ── Local chunking ────────────────────────────────────────────────────────────
local_chunking_enabled: ${CFG_CHUNKING}
chunk_size_tokens: ${CFG_CHUNK_SIZE}
chunk_overlap_tokens: ${CFG_OVERLAP}

# ── Supported file extensions ─────────────────────────────────────────────────
supported_extensions:
  - .txt
  - .md
  - .log
  - .csv
  - .pdf
  - .docx
  - .pptx
  - .xlsx
  - .png
  - .jpg
  - .jpeg
  - .tiff
  - .bmp
EOF

success "config.yaml written"

# ── Step 5 — Test Hindsight connection ────────────────────────────────────────
section "Step 5  Testing Hindsight connection"

info "Pinging ${CFG_SERVER_URL}…"
if curl -sf --max-time 5 "${CFG_SERVER_URL}/v1/default/banks" -o /dev/null 2>&1; then
  success "Connected to Hindsight at ${CFG_SERVER_URL}"
else
  warn "Could not reach ${CFG_SERVER_URL}."
  warn "Make sure Hindsight is running before starting the daemon."
fi

# ── Step 6 — Systemd user service (optional) ──────────────────────────────────
section "Step 6  Systemd daemon (optional)"

echo ""
echo -e "  ${DIM}A systemd user service lets the daemon start automatically at login${RST}"
echo -e "  ${DIM}(or at boot with lingering enabled) without requiring root.${RST}"
echo ""

SETUP_SYSTEMD=false
if ask_yn "Set up a systemd user service?" "n"; then
  SETUP_SYSTEMD=true
fi

if $SETUP_SYSTEMD; then
  SERVICE_DIR="${HOME}/.config/systemd/user"
  SERVICE_FILE="${SERVICE_DIR}/hindsight-scan-ingest.service"
  mkdir -p "$SERVICE_DIR"

  if [[ -d "$VENV_DIR" ]]; then
    EXEC_CMD="${VENV_DIR}/bin/python3 ${INSTALL_DIR}/main.py"
  else
    EXEC_CMD="${PY} ${INSTALL_DIR}/main.py"
  fi

  cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Hindsight Scan Ingest — document ingestion daemon
Documentation=https://github.com/winoiknow/hindsight-scan-ingest
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${EXEC_CMD}
Restart=on-failure
RestartSec=15
StandardOutput=journal
StandardError=journal
SyslogIdentifier=hindsight-ingest

[Install]
WantedBy=default.target
EOF

  success "Service file written to ${SERVICE_FILE}"

  if systemctl --user daemon-reload 2>/dev/null; then
    success "systemd daemon reloaded"
  else
    warn "Could not reload systemd (not running as a user session?). Run manually:"
    warn "   systemctl --user daemon-reload"
  fi

  echo ""
  echo -e "  ${DIM}Enable and start the service:${RST}"
  echo -e "  ${YLW}  systemctl --user enable --now hindsight-scan-ingest${RST}"
  echo ""
  echo -e "  ${DIM}Start on boot even when not logged in (requires root once):${RST}"
  echo -e "  ${YLW}  sudo loginctl enable-linger ${USER}${RST}"
  echo ""
  echo -e "  ${DIM}View live logs:${RST}"
  echo -e "  ${YLW}  journalctl --user -fu hindsight-scan-ingest${RST}"
  echo ""

  if ask_yn "Enable and start the service now?" "y"; then
    systemctl --user enable --now hindsight-scan-ingest \
      && success "Service enabled and started" \
      || warn "Could not start service — check: systemctl --user status hindsight-scan-ingest"
  fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GRN}${BOLD}"
cat <<'DONE'
   ╔══════════════════════════════════════════════════════════════╗
   ║                                                              ║
   ║    Installation complete!                                    ║
   ║                                                              ║
   ╚══════════════════════════════════════════════════════════════╝
DONE
echo -e "${RST}"

echo -e "  ${BOLD}Quick start:${RST}"
if [[ -d "$VENV_DIR" ]]; then
  echo -e "  ${GRN}source .venv/bin/activate${RST}"
fi
echo -e "  ${GRN}python3 main.py --once${RST}         # single scan pass"
echo -e "  ${GRN}python3 main.py${RST}                # continuous daemon"
echo -e "  ${GRN}python3 main.py --help${RST}         # all options"
echo ""
echo -e "  ${DIM}Hindsight control panel:  ${CFG_SERVER_URL/8888/9999}${RST}"
echo -e "  ${DIM}Config file:              ${CONFIG_PATH}${RST}"
echo -e "  ${DIM}Manifest database:        ${INSTALL_DIR}/ingestion_manifest.db${RST}"
echo ""
