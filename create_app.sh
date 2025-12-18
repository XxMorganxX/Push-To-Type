#!/bin/bash
# Script to create a macOS .app bundle for PTT Transcription

APP_NAME="PTT Transcription"
BUNDLE_ID="com.ptt.transcription"
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
APP_DIR="$HOME/Desktop/${APP_NAME}.app"

echo "🔨 Creating macOS application bundle..."

# Create app bundle structure
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# Generate icon
echo "🎨 Generating app icon..."
cd "$PROJECT_DIR"
python3 create_icon.py

# Copy icon if it was created
if [ -f "$PROJECT_DIR/AppIcon.icns" ]; then
    cp "$PROJECT_DIR/AppIcon.icns" "$APP_DIR/Contents/Resources/"
    echo "✅ Icon added to app bundle"
else
    echo "⚠️  No icon created, app will use default icon"
fi

# Create Info.plist
cat > "$APP_DIR/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>launch</string>
    <key>CFBundleIdentifier</key>
    <string>${BUNDLE_ID}</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>LSUIElement</key>
    <false/>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# Create launch script
cat > "$APP_DIR/Contents/MacOS/launch" << 'EOF'
#!/bin/bash

# Get project directory (stored in Resources)
PROJECT_DIR=$(cat "$( dirname "${BASH_SOURCE[0]}" )"/../Resources/project_path.txt)

# Open Terminal and run the project
osascript << SCRIPT
tell application "Terminal"
    activate
    do script "cd '$PROJECT_DIR' && source venv/bin/activate && echo '🚀 Starting PTT Transcription...' && echo '' && python main.py"
end tell
SCRIPT
EOF

# Store project directory path
echo "$PROJECT_DIR" > "$APP_DIR/Contents/Resources/project_path.txt"

# Make launch script executable
chmod +x "$APP_DIR/Contents/MacOS/launch"

echo "✅ Application created at: $APP_DIR"
echo ""
echo "📱 You can now:"
echo "   1. Double-click '$APP_NAME.app' on your Desktop to launch"
echo "   2. Drag it to your Applications folder"
echo "   3. Add it to your Dock"
echo ""
echo "🎤 The app will open Terminal and start the PTT software"

