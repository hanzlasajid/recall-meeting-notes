#!/bin/bash
# Recall - double-click to pick a recording, or run: ./Recall.command video.mp4
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "First run - setting up the tool..."
  bash ./setup_mac.command || exit 1
fi
.venv/bin/python -m recall "$@"
echo
read -r -p "Press Enter to close this window." _
