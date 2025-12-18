# 🎤 PTT Transcription

**Push-to-Talk Speech-to-Text** that types wherever your cursor is.

Hold a keybind, speak, release — your speech is instantly typed into any application. Perfect for coding, writing, or any situation where you want to dictate text without switching windows.

https://github.com/yourusername/ptt-transcription

---

## ✨ Features

- **🎯 Real-time transcription** - Text appears as you speak
- **⌨️ Direct keyboard injection** - Works in any app (no clipboard interference)
- **🟢🔴🟡 Visual indicator** - On-screen dot shows app state (green=ready, red=recording, yellow=processing)
- **🎨 Customizable keybinds** - Default: Left Shift + Right Shift
- **📝 Smart punctuation** - Automatic word replacements (e.g., "slash" → "/")
- **🚫 No clipboard pollution** - Uses paste mode with automatic clipboard restore
- **💤 Prevents system sleep** - Built-in caffeinate support
- **📦 macOS App bundle** - Double-click to launch

## 🎬 Demo

```
Hold [Left Shift + Right Shift] → Speak → Release → Text appears!
```

**Indicator states:**
- 🟢 **Green** - App is running and ready for input
- 🔴 **Red** - Currently recording (PTT held)
- 🟡 **Yellow** - Processing final transcription (between turns)

---

## 🚀 Quick Start

### Prerequisites

- **macOS** (uses Quartz/CGEvents for keyboard injection)
- **Python 3.9+**
- **PortAudio** (for microphone access)
- **AssemblyAI API Key** ([Free tier available](https://www.assemblyai.com/))

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/ptt-transcription.git
cd ptt-transcription

# 2. Install PortAudio
brew install portaudio

# 3. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Set up your API key
# Option A: Environment variable
export ASSEMBLYAI_API_KEY="your_api_key_here"

# Option B: Add to config.json
# Edit config.json and replace "in_env" with your actual key

# 6. Grant permissions
# System Preferences → Security & Privacy → Accessibility
# Add Terminal (or your terminal app)
```

### Running

```bash
# Method 1: Command line (recommended, includes caffeinate)
./run.sh

# Method 2: Direct Python
python main.py

# Method 3: Double-click launcher
# Double-click launch_ptt.command

# Method 4: macOS App (one-time setup)
./create_app.sh
# Then double-click "PTT Transcription.app" on your Desktop
```

---

## 📖 Usage

### Basic Operation

1. **Start the app** using any method above
2. **Hold Left Shift + Right Shift** simultaneously
3. **Speak** - the red indicator appears in top-right
4. **Release** either shift key to stop
5. **Text appears** at your cursor position

### Configuration

Edit `config.json` to customize:

#### Keybinds
```json
{
  "keybinds": {
    "ptt": "leftshift+rightshift"
  }
}
```

#### Indicator
```json
{
  "indicator": {
    "enabled": true,
    "size": 16,
    "position_x": 30,                        // Pixels from right edge
    "position_y": 30,                        // Pixels from top
    "ready_color": [0.2, 0.8, 0.2, 0.9],     // RGBA green - app ready
    "active_color": [1.0, 0.2, 0.2, 0.95],   // RGBA red - recording
    "processing_color": [1.0, 0.8, 0.0, 0.9] // RGBA yellow - processing
  }
}
```

#### Typing Behavior
```json
{
  "typing": {
    "mode": "paste",              // "paste" or "keystroke"
    "preserve_clipboard": true,   // Restore clipboard after paste
    "delay_ms": 5                 // Character delay (keystroke mode)
  }
}
```

#### Word Replacements
```json
{
  "word_replacements": {
    "slash": "/",
    "colon": ":",
    "dot": "."
  },
  "phrase_replacements": {
    "forward slash": "/",
    "back slash": "\\"
  },
  "word_joiners": ["/", "-", ":", "@", "#"]
}
```

#### Audio Settings
```json
{
  "audio": {
    "chunk_duration_ms": 10,
    "min_send_ms": 20,
    "prebuffer_ms": 100
  }
}
```

---

## 🏗️ Architecture

### Core Components

- **`main.py`** - Main application loop, PTT management
- **`core/unicode_injector.py`** - Keyboard injection via CGEvents/clipboard
- **`core/ptt_keybind_manager.py`** - Pynput-based keybind detection
- **`core/event_tap_listener.py`** - Quartz event tap for reliable L+R shift detection
- **`core/ptt_indicator.py`** - On-screen recording indicator

### How It Works

1. **Keybind Detection**: Dual listeners (pynput + Quartz) ensure reliable PTT detection
2. **Audio Capture**: PyAudio streams mic input to AssemblyAI WebSocket
3. **Transcription**: Real-time streaming transcription with word-level confidence
4. **Text Processing**: Word replacements, phrase detection, joiner handling
5. **Injection**: 
   - **Paste mode** (default): Uses clipboard + Cmd+V (fewer HID events, cleaner shutdown)
   - **Keystroke mode**: Per-character CGEvents (more direct, no clipboard usage)

### Why Two Injection Modes?

- **Paste mode**: Prevents "character burst" on shutdown/Ctrl+C. Automatically restores clipboard.
- **Keystroke mode**: True per-character typing (useful for apps that have issues with paste)

---

## 🎨 Creating a macOS App

### Generate the App Bundle

```bash
./create_app.sh
```

This creates `PTT Transcription.app` on your Desktop with a custom microphone icon.

### Customize the Icon

```bash
# Option 1: Better icon with Pillow
pip install Pillow
python3 create_icon.py
./create_app.sh

# Option 2: Use your own image
# See ICON_GUIDE.md for details
```

---

## 🛠️ Development

### Install dev dependencies

```bash
pip install -r requirements-dev.txt
```

### Code formatting

```bash
black .
```

### Type checking

```bash
mypy main.py core/
```

### Project Structure

```
ptt-transcription/
├── main.py                  # Main application
├── config.json              # User configuration
├── requirements.txt         # Production dependencies
├── requirements-dev.txt     # Development dependencies
├── core/
│   ├── unicode_injector.py  # Keyboard injection
│   ├── ptt_keybind_manager.py
│   ├── event_tap_listener.py
│   └── ptt_indicator.py
├── create_app.sh            # Build macOS app
├── create_icon.py           # Generate app icon
├── launch_ptt.command       # Double-click launcher
├── run.sh                   # CLI launcher with caffeinate
└── ICON_GUIDE.md           # Icon customization guide
```

---

## 🐛 Troubleshooting

### No microphone input detected
```bash
# Check permissions
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
```

### PTT keybind not working
```bash
# Grant Accessibility permissions
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
# Add Terminal (or your terminal app) to the list
```

### Text doesn't appear / types in wrong place
- Make sure target app has focus
- Try switching typing mode in config: `"mode": "keystroke"` or `"mode": "paste"`

### Indicator doesn't show
- Check `config.json`: `"indicator": { "enabled": true }`
- macOS may cache the indicator window - restart the app

### Characters "burst" on Ctrl+C shutdown
- Use **paste mode** (default): `"mode": "paste"` in config.json
- This drastically reduces HID event buffering

### WebSocket connection fails
```bash
# Check API key
echo $ASSEMBLYAI_API_KEY
# Or verify in config.json
```

---

## 📝 License

MIT License - See LICENSE file for details

---

## 🙏 Acknowledgments

- **[AssemblyAI](https://www.assemblyai.com/)** - Fast, accurate real-time transcription
- **PyObjC** - macOS Quartz/Cocoa bindings
- **pynput** - Cross-platform keyboard control

---

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📮 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/ptt-transcription/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/ptt-transcription/discussions)

---

## 🗺️ Roadmap

- [ ] Windows support
- [ ] Linux support  
- [ ] Custom vocabulary/boost words
- [ ] Multiple keybind profiles
- [ ] Hotkey for pause/resume without releasing PTT
- [ ] System tray integration
- [ ] Audio passthrough/monitoring

---

Made with ❤️ for developers who want to dictate code
