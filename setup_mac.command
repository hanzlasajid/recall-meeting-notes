#!/bin/bash
# Recall - one-time setup for macOS. Double-click (or run: bash setup_mac.command).
set -e
cd "$(dirname "$0")"
echo "================================================"
echo "  Recall - one-time setup for macOS"
echo "================================================"
echo

# ---- 1. Find Python 3.10+ with Tk (the file picker / settings window needs Tk) ----
PY=""
for c in python3.12 python3.11 python3.13 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  if command -v brew >/dev/null 2>&1; then
    echo "Python 3.10+ not found - installing Python 3.12 with Homebrew..."
    HOMEBREW_NO_ASK=1 brew install python@3.12 python-tk@3.12
    PY="$(brew --prefix)/bin/python3.12"
  else
    echo "Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/macos/"
    echo "(the python.org installer includes everything this tool needs), then run this setup again."
    read -r -p "Press Enter to close." _; exit 1
  fi
fi
echo "Using Python: $PY ($("$PY" --version))"
if ! "$PY" -c 'import tkinter' 2>/dev/null; then
  echo
  echo "Note: this Python has no Tk, so the tool will ask in the Terminal instead of showing windows."
  echo "      For windows: brew install python-tk@$("$PY" -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
fi

# ---- 2. Private environment + libraries ----
if [ ! -x .venv/bin/python ]; then
  echo; echo "Creating the tool's own Python environment in .venv ..."
  "$PY" -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -q --upgrade pip
echo; echo "Installing the tool's libraries (a few minutes the first time)..."
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt

# ---- 3. Drag-and-drop app ----
echo; echo "Building the 'Recall' app you can drop recordings on..."
rm -rf "Recall.app" "Meeting Notes.app"
osacompile -o "Recall.app" mac/Recall.applescript
chmod +x Recall.command setup_mac.command 2>/dev/null || true

echo; echo "=== Your hardware and the transcription model it will use ==="
.venv/bin/python -m recall --hardware
echo
echo "Setup finished. In this folder you now have 'Recall.app':"
echo "  - drag a recording onto it (you can also drag the app to your Dock and drop files there), or"
echo "  - double-click it and choose a recording."
echo "Keep the app in this folder - it runs the tool from here."
echo "No Anthropic API key? Recall can write the report with a free local AI instead"
echo "(it offers to install Ollama and a model the first time)."
read -r -p "Press Enter to close." _
