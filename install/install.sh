#!/usr/bin/env bash
# Zero-Cost AI Operating System for Obsidian — Linux installer.
#   ./install/install.sh [--gpu] [--service] [--python python3.12]
#
#   --gpu      also install the CUDA-12 GPU embedding stack (NVIDIA box)
#   --service  also install + enable the systemd unit (uses sudo)
#   --python   python interpreter to build the venv with (default: python3)
#
# Idempotent: safe to re-run. Never overwrites an existing settings.json.
set -euo pipefail

GPU=0; SERVICE=0; PY=python3
while [ $# -gt 0 ]; do
  case "$1" in
    --gpu) GPU=1 ;;
    --service) SERVICE=1 ;;
    --python) PY="$2"; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac; shift
done

# Repo root = parent of this script's dir.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
echo "==> Repo: $ROOT"

command -v "$PY" >/dev/null || { echo "ERROR: '$PY' not found. Install Python 3.12+."; exit 1; }
echo "==> Python: $("$PY" --version)"

# 1) venv
if [ ! -x ".venv/bin/python" ]; then
  echo "==> Creating .venv"
  "$PY" -m venv .venv
fi
VENV_PY=".venv/bin/python"

# 2) dependencies
echo "==> Installing requirements"
"$VENV_PY" -m pip install --upgrade pip >/dev/null
"$VENV_PY" -m pip install -r requirements.txt

# 3) GPU embedding stack (CUDA-12 build — the latest onnxruntime-gpu targets CUDA 13)
if [ "$GPU" = "1" ]; then
  echo "==> Installing CUDA-12 GPU embedding stack"
  "$VENV_PY" -m pip uninstall -y fastembed onnxruntime 2>/dev/null || true
  "$VENV_PY" -m pip install "fastembed-gpu" "onnxruntime-gpu==1.22.0" \
             "nvidia-cudnn-cu12" "nvidia-cublas-cu12" "nvidia-cuda-runtime-cu12"
  echo "    Set  \"embedding_device\": \"cuda\"  in settings.json to use it."
  echo "    CUDAExecutionProvider available:"
  "$VENV_PY" -c "import onnxruntime as o; print('   ', o.get_available_providers())" || true
fi

# 4) settings.json (never overwrite an existing one)
CFG="assistant_core/config/settings.json"
EX="assistant_core/config/settings.example.json"
if [ ! -f "$CFG" ]; then
  cp "$EX" "$CFG"
  echo "==> Created $CFG from the example — EDIT IT (vault_path + at least one provider key)."
else
  echo "==> $CFG already exists — left untouched."
fi

# 5) optional systemd service
if [ "$SERVICE" = "1" ]; then
  USER_NAME="$(id -un)"; GROUP_NAME="$(id -gn)"
  UNIT="/etc/systemd/system/assistant.service"
  echo "==> Writing $UNIT (sudo)"
  sudo tee "$UNIT" >/dev/null <<UNITEOF
[Unit]
Description=AI Assistant Service
After=network.target

[Service]
Type=simple
User=$USER_NAME
Group=$GROUP_NAME
WorkingDirectory=$ROOT
ExecStart=$ROOT/.venv/bin/python assistant.py
Restart=always
RestartSec=5
StandardOutput=append:$ROOT/logs/service.log
StandardError=append:$ROOT/logs/service.log

[Install]
WantedBy=multi-user.target
UNITEOF
  mkdir -p "$ROOT/logs"
  sudo systemctl daemon-reload
  sudo systemctl enable --now assistant
  echo "==> assistant.service enabled. Status: $(systemctl is-active assistant)"
  echo "    Restart with: sudo systemctl restart assistant"
fi

echo
echo "==> Done."
echo "    Next: edit $CFG, then run:  .venv/bin/python -m assistant_core --terminal"
echo "    Headless/service mode runs automatically with no TTY."
