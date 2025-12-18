#!/bin/bash
# PTT Transcription Launcher
# This script activates the virtual environment and starts the application

# Get the directory where this script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Change to the project directory
cd "$DIR"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found!"
    echo "Please run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    read -p "Press Enter to exit..."
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Check if API key is set
if [ -z "$ASSEMBLYAI_API_KEY" ]; then
    echo "⚠️  Warning: ASSEMBLYAI_API_KEY not set in environment"
    echo "Make sure it's configured in config.json or set it here:"
    echo ""
fi

# Run the application
echo "🚀 Starting PTT Transcription..."
echo ""
python main.py

# Keep window open on exit
echo ""
read -p "Press Enter to close..."



