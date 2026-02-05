#!/bin/bash
# Mac-friendly: use a venv so pip install works (avoids "externally-managed-environment")
set -e
cd "$(dirname "$0")"

VENV=".venv"
if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV"
fi
source "$VENV/bin/activate"

echo "Installing dependencies..."
pip install -q -r requirements.txt

# Server tries port 8080, then 8081, then 8082 if in use
echo ""
echo "=========================================="
echo "  Quant Strategies server"
echo "=========================================="
echo "  Open the URL shown below (8080, or 8081 if 8080 is in use)."
echo "=========================================="
echo ""
python3 server.py
