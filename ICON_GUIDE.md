# App Icon Guide

## Current Icon

Your PTT Transcription app now has a custom icon (red microphone on a light background).

## Using a Custom Icon

If you want to use your own icon image:

### Option 1: Using an existing image file

1. Find or create an image (PNG, JPG, etc.) - ideally 1024x1024px or larger
2. Convert it to `.icns` format using one of these methods:

#### Method A: Using Pillow (recommended)

```bash
# Install Pillow if you haven't
source venv/bin/activate
pip install Pillow

# Then just run the icon script - it will create a better quality icon
python3 create_icon.py
```

#### Method B: Using online converter
- Go to https://cloudconvert.com/png-to-icns
- Upload your image
- Download the `.icns` file
- Save it as `AppIcon.icns` in the project folder

#### Method C: Using macOS tools
```bash
# Create iconset directory
mkdir AppIcon.iconset

# Copy your image (1024x1024) to:
cp your_icon.png AppIcon.iconset/icon_512x512@2x.png

# You should create multiple sizes, but minimally:
# - icon_16x16.png (16x16)
# - icon_32x32.png (32x32) 
# - icon_128x128.png (128x128)
# - icon_256x256.png (256x256)
# - icon_512x512.png (512x512)
# - icon_512x512@2x.png (1024x1024)

# Convert to icns
iconutil -c icns AppIcon.iconset -o AppIcon.icns

# Clean up
rm -rf AppIcon.iconset
```

3. After creating `AppIcon.icns`, recreate the app:

```bash
./create_app.sh
```

### Option 2: Improve the default icon with Pillow

Install Pillow for better icon quality:

```bash
source venv/bin/activate
pip install Pillow
python3 create_icon.py
./create_app.sh
```

This will create a higher-quality microphone icon with anti-aliasing and better colors.

## Refreshing the Icon

If you update the icon and it doesn't appear immediately:

```bash
# Refresh Finder
touch "$HOME/Desktop/PTT Transcription.app"
killall Finder

# Or restart Dock
killall Dock
```

## Icon Specifications

For best results, your custom icon should:
- Be square (same width and height)
- Be at least 1024x1024 pixels
- Have transparency (PNG with alpha channel)
- Use colors that work on both light and dark backgrounds
- Be simple and recognizable at small sizes (16x16)

## Icon Files Location

- Source icon: `AppIcon.icns` (in project folder)
- App bundle icon: `~/Desktop/PTT Transcription.app/Contents/Resources/AppIcon.icns`

