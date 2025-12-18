#!/usr/bin/env python3
"""
Generate a simple icon for the PTT Transcription app.
Creates a red microphone icon on a rounded square background.
"""

import os
import subprocess
from pathlib import Path

def create_icon():
    """Create an icon using Python Imaging (PIL) or fallback to iconutil."""
    
    # Try using PIL/Pillow if available
    try:
        from PIL import Image, ImageDraw
        return create_icon_with_pil()
    except ImportError:
        print("📦 Pillow not installed, creating simple icon with iconutil...")
        return create_icon_with_iconutil()

def create_icon_with_pil():
    """Create icon using PIL/Pillow."""
    from PIL import Image, ImageDraw
    
    # Create iconset directory
    iconset_dir = Path(__file__).parent / "AppIcon.iconset"
    iconset_dir.mkdir(exist_ok=True)
    
    # Icon sizes needed for macOS
    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    
    for size, filename in sizes:
        img = create_mic_icon(size)
        img.save(iconset_dir / filename)
    
    # Convert to icns
    icns_path = Path(__file__).parent / "AppIcon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)], check=True)
    
    # Clean up iconset
    import shutil
    shutil.rmtree(iconset_dir)
    
    print(f"✅ Icon created: {icns_path}")
    return icns_path

def create_mic_icon(size):
    """Create a microphone icon at the specified size."""
    from PIL import Image, ImageDraw
    
    # Create image with transparency
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Calculate dimensions
    padding = size * 0.15
    
    # Draw rounded square background
    bg_color = (240, 240, 245, 255)
    corner_radius = size * 0.2
    draw.rounded_rectangle(
        [(0, 0), (size, size)],
        radius=corner_radius,
        fill=bg_color
    )
    
    # Draw microphone shape (simple circle for mic head)
    mic_center_x = size / 2
    mic_center_y = size / 2.3
    mic_radius = size * 0.2
    
    # Mic color (red like the indicator)
    mic_color = (255, 51, 51, 255)
    
    # Draw mic capsule (circle)
    draw.ellipse(
        [
            mic_center_x - mic_radius,
            mic_center_y - mic_radius * 1.2,
            mic_center_x + mic_radius,
            mic_center_y + mic_radius * 0.8
        ],
        fill=mic_color
    )
    
    # Draw mic stand (line)
    stand_width = size * 0.05
    stand_height = size * 0.2
    draw.rectangle(
        [
            mic_center_x - stand_width / 2,
            mic_center_y + mic_radius * 0.8,
            mic_center_x + stand_width / 2,
            mic_center_y + mic_radius * 0.8 + stand_height
        ],
        fill=(80, 80, 90, 255)
    )
    
    # Draw base
    base_width = size * 0.25
    base_height = size * 0.08
    draw.ellipse(
        [
            mic_center_x - base_width / 2,
            mic_center_y + mic_radius * 0.8 + stand_height,
            mic_center_x + base_width / 2,
            mic_center_y + mic_radius * 0.8 + stand_height + base_height
        ],
        fill=(80, 80, 90, 255)
    )
    
    return img

def create_icon_with_iconutil():
    """Fallback: create a simple colored icon without PIL."""
    iconset_dir = Path(__file__).parent / "AppIcon.iconset"
    iconset_dir.mkdir(exist_ok=True)
    
    # Create a simple red square PNG using sips (macOS built-in)
    for size, filename in [(512, "icon_512x512.png"), (1024, "icon_512x512@2x.png")]:
        # Create a simple solid color image
        png_path = iconset_dir / filename
        # Use Python to create a minimal PNG
        create_simple_png(png_path, size)
    
    # Convert to icns
    icns_path = Path(__file__).parent / "AppIcon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)], check=True)
    
    # Clean up
    import shutil
    shutil.rmtree(iconset_dir)
    
    print(f"✅ Simple icon created: {icns_path}")
    return icns_path

def create_simple_png(path, size):
    """Create a minimal PNG file with a red circle."""
    # Minimal PNG with red circle (using raw bytes)
    import struct
    import zlib
    
    # Create RGBA data (red circle on transparent background)
    data = bytearray()
    center = size // 2
    radius = size // 3
    
    for y in range(size):
        data.append(0)  # Filter byte for scanline
        for x in range(size):
            dx = x - center
            dy = y - center
            if dx*dx + dy*dy < radius*radius:
                # Red
                data.extend([255, 51, 51, 255])
            else:
                # Transparent
                data.extend([0, 0, 0, 0])
    
    # Compress
    compressed = zlib.compress(bytes(data))
    
    # Write PNG
    with open(path, 'wb') as f:
        # PNG signature
        f.write(b'\x89PNG\r\n\x1a\n')
        
        # IHDR chunk
        ihdr = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)
        write_chunk(f, b'IHDR', ihdr)
        
        # IDAT chunk
        write_chunk(f, b'IDAT', compressed)
        
        # IEND chunk
        write_chunk(f, b'IEND', b'')

def write_chunk(f, chunk_type, data):
    """Write a PNG chunk."""
    import struct
    import zlib
    
    f.write(struct.pack('>I', len(data)))
    f.write(chunk_type)
    f.write(data)
    crc = zlib.crc32(chunk_type + data) & 0xffffffff
    f.write(struct.pack('>I', crc))

if __name__ == "__main__":
    try:
        icon_path = create_icon()
        print(f"🎨 Icon created successfully at: {icon_path}")
    except Exception as e:
        print(f"❌ Error creating icon: {e}")
        import traceback
        traceback.print_exc()

