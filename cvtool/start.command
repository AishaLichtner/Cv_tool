#!/bin/bash
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 nicht gefunden / not found. Install: https://www.python.org/downloads/"
  read -n 1 -s -r -p "Taste druecken / press any key"; exit 1
fi
if [ ! -x ".venv/bin/python" ]; then
  echo "Erster Start: Einrichtung ... / First start: setting up ..."
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
.venv/bin/python app.py
