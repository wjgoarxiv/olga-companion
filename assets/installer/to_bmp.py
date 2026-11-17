"""Convert the rendered installer PNGs to the 24-bit BMPs NSIS and WiX expect."""
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE.parent.parent / "src-tauri" / "installer"
OUT.mkdir(parents=True, exist_ok=True)
for png in sorted((HERE / "png").glob("*.png")):
    target = OUT / (png.stem + ".bmp")
    Image.open(png).convert("RGB").save(target, "BMP")
    print(target.name, Image.open(target).size)
