import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw

brain_dir = Path("/Users/alper/.gemini/antigravity/brain/8b432e4d-08ae-4f21-9c65-eedf6a026e01")
out_dir = Path("src/warden/assets")

png_files = list(brain_dir.glob("mascot_*.png"))

for png_path in png_files:
    if "clean" in png_path.name:
        continue

    base_name = png_path.stem.rsplit("_", 1)[0]
    bmp_path = brain_dir / f"{base_name}.bmp"
    svg_path = out_dir / f"warden-logo-{base_name.split('_')[1]}.svg"

    print(f"Processing {png_path.name}...")

    img = Image.open(png_path).convert("RGBA")

    # Create white background in case of transparency
    white_bg = Image.new("RGBA", img.size, "WHITE")
    white_bg.paste(img, (0, 0), img)

    img = white_bg.convert("RGB")

    # Floodfill from the corners to remove generated backgrounds
    # Assuming the corners are the background
    ImageDraw.floodfill(img, xy=(0, 0), value=(255, 255, 255), thresh=40)
    ImageDraw.floodfill(img, xy=(img.width - 1, 0), value=(255, 255, 255), thresh=40)
    ImageDraw.floodfill(img, xy=(0, img.height - 1), value=(255, 255, 255), thresh=40)
    ImageDraw.floodfill(img, xy=(img.width - 1, img.height - 1), value=(255, 255, 255), thresh=40)

    # Convert to Grayscale
    gray = img.convert("L")

    # Strict Thresholding
    # Keep only the very dark lines
    binary = gray.point(lambda p: 0 if p < 100 else 255, mode="1")

    binary.save(bmp_path)

    print(f"Tracing {bmp_path.name} to {svg_path.name}...")
    subprocess.run(["potrace", str(bmp_path), "-s", "-o", str(svg_path), "-t", "5", "--color", "#000000"], check=True)

    os.remove(bmp_path)
    print(f"Generated {svg_path}")
