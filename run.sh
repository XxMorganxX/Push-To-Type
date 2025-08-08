#!/bin/bash
# Run the Push-to-Talk transcription with keyboard injection
# Keeps the Mac awake to avoid event tap/websocket issues after long idle

set -euo pipefail
cd "$(dirname "$0")"
source venv/bin/activate

# Prevent system/app nap and sleep while running
exec caffeinate -isu python main.py