#!/usr/bin/env bash
# Setup script for Pi Webcam RTSP Streamer
# Run on Raspberry Pi 3B+ with: sudo bash setup.sh

set -euo pipefail

MEDIAMTX_VERSION="v1.17.0"
MEDIAMTX_ARCH="linux_armv7"
MEDIAMTX_URL="https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_VERSION}/mediamtx_${MEDIAMTX_VERSION}_${MEDIAMTX_ARCH}.tar.gz"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Pi Webcam RTSP Streamer Setup ==="

# Install system dependencies
echo "[1/3] Installing system dependencies..."
apt-get update -qq
apt-get install -y ffmpeg v4l-utils python3 python3-venv

# Download mediamtx
if [ -f "${SCRIPT_DIR}/mediamtx" ]; then
    echo "[2/3] mediamtx binary already exists, skipping download."
else
    echo "[2/3] Downloading mediamtx ${MEDIAMTX_VERSION} (${MEDIAMTX_ARCH})..."
    TMP_DIR="$(mktemp -d)"
    curl -fsSL "${MEDIAMTX_URL}" -o "${TMP_DIR}/mediamtx.tar.gz"
    tar -xzf "${TMP_DIR}/mediamtx.tar.gz" -C "${TMP_DIR}"
    mv "${TMP_DIR}/mediamtx" "${SCRIPT_DIR}/mediamtx"
    chmod +x "${SCRIPT_DIR}/mediamtx"
    rm -rf "${TMP_DIR}"
    echo "    Downloaded to ${SCRIPT_DIR}/mediamtx"
fi

# Set up Python virtual environment
echo "[3/3] Setting up Python virtual environment..."
if [ ! -d "${SCRIPT_DIR}/venv" ]; then
    python3 -m venv "${SCRIPT_DIR}/venv"
fi
"${SCRIPT_DIR}/venv/bin/pip" install --quiet -r "${SCRIPT_DIR}/requirements.txt"

echo ""
echo "=== Setup complete ==="
echo "Verify your camera is connected:"
echo "  v4l2-ctl --list-devices"
echo ""
echo "Start the server:"
echo "  cd ${SCRIPT_DIR}"
echo "  venv/bin/python server.py"
