#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f ".venv/bin/activate" ]; then
    echo "Virtual environment non trovato, lo creo..."
    python3 -m venv .venv
fi
source .venv/bin/activate

if ! python -c "import ruff" 2>/dev/null; then
    echo "Dipendenze non installate, le installo..."
    pip install -r requirements.dev.txt
fi

echo "=== ruff ==="
ruff check .

echo "=== mypy ==="
mypy redberry_webkit

echo "=== pytest ==="
pytest

echo "Tutti i check sono passati."
