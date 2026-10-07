#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/download_models.py
exec caffeinate -i python server.py --https
