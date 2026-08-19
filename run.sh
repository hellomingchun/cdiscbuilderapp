#!/usr/bin/env bash
# ==============================================================================
# CDISC Builder v2 - Standalone App Launcher (Linux / macOS)
# ==============================================================================

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "========================================================"
echo "  Starting CDISC Builder v2 (Yamaa Schema Standard)"
echo "========================================================"

# Check if Python is available
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "Error: Python 3.9+ is required but not found on your system."
    exit 1
fi

PY_BIN="$(command -v python3 || command -v python)"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    $PY_BIN -m venv .venv
    source .venv/bin/activate
    echo "Installing CDISC Builder v2 dependencies..."
    pip install --upgrade pip
    pip install -e .
else
    source .venv/bin/activate
fi

# Launch the Application
echo "Launching CDISC Builder Web UI..."
python -m cdiscbuilderv2.cli app --host 127.0.0.1 --port 8000 --open-browser
