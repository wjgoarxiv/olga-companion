"""Render assets/cover.png.

Deliberately matched to the visual language of wjgoarxiv/youtube-digest-skill:
2560x1280, near-black field, soft off-centre colour blooms, heavy film grain,
and a centred monospace lockup. The hue is shifted from that repo's red to a
cyan/teal reading, which is the convention for flow and pressure work.

Regenerate with:  python assets/make_cover.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 2560, 1280
OUT = Path(__file__).parent / "cover.png"

# (centre_x, centre_y, radius, (r, g, b), peak_intensity) in pixel space.
BLOOMS = [
    (1180, 300, 900, (0, 190, 205), 0.85),   # primary teal, upper centre-right
    (1980, 560, 780, (0, 120, 190), 0.55),   # cooler blue, right
    (520, 980, 820, (70, 60, 170), 0.42),    # indigo, lower left
    (2350, 1150, 620, (0, 90, 120), 0.30),   # deep cyan, corner lift
]

BASE = np.array([9, 10, 12], dtype=np.float64)  # near-black, very slightly cool


def render_field() -> np.ndarray:
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float64)
    canvas = np.repeat(BASE[None, None, :], H, axis=0).repeat(W, axis=1)

    for cx, cy, radius, colour, peak in BLOOMS:
        d = np.hypot(xs - cx, ys - cy) / radius
        # Smooth falloff; the exponent keeps the core soft rather than a disc.
        falloff = np.clip(1.0 - d, 0.0, 1.0) ** 2.2
        canvas += np.array(colour, dtype=np.float64)[None, None, :] * (falloff * peak)[..., None]

    return canvas


def add_grain(canvas: np.ndarray, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # Luminance-coupled grain: heavier in the lit blooms, near-absent in black,
    # which is what makes the reference read as film rather than as noise.
    luma = canvas.mean(axis=2, keepdims=True) / 255.0
    grain = rng.normal(0.0, 1.0, size=(H, W, 1))
    return canvas + grain * (7.0 + 16.0 * luma)


BRAND_MONO = (
    Path(__file__).parent / "fonts" / "MesloLGSNerdFontMono-Regular.ttf"
)


def load_mono(size: int) -> ImageFont.FreeTypeFont:
    """The application's own mono face first.

    The cover fronts the README; setting it in Consolas while the app is set in
    MesloLGS makes the two read as different products. System faces remain only
    as a fallback for a machine without the repo's font files.
    """
    candidates: list[str] = []
    if BRAND_MONO.exists():
        candidates.append(str(BRAND_MONO))
    else:
        print(f"warning: {BRAND_MONO.name} missing; falling back to a system mono face")
    candidates += ["consolab.ttf", "consola.ttf", "cour.ttf", "DejaVuSansMono-Bold.ttf"]

    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    canvas = add_grain(render_field())
    image = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8), mode="RGB")
    draw = ImageDraw.Draw(image)

    title_font = load_mono(210)
    tag_font = load_mono(62)

    title = "olga-companion"
    tagline = "Supervise OLGA runs with evidence you can check."

    tw = draw.textbbox((0, 0), title, font=title_font)
    tx = (W - (tw[2] - tw[0])) // 2 - tw[0]
    ty = int(H * 0.42)

    # Mark sits above the lockup. Rendered from assets/logo/mark.svg by
    # assets/logo/render.mjs -- Pillow cannot rasterise the mask the gas void
    # depends on, so the glyph is prepared as PNG rather than redrawn here.
    glyph_path = Path(__file__).parent / "logo" / "mark-white-260.png"
    if glyph_path.exists():
        glyph = Image.open(glyph_path).convert("RGBA")
        image.paste(glyph, ((W - glyph.width) // 2, ty - glyph.height - 30), glyph)
    else:
        print(f"warning: {glyph_path.name} missing; cover rendered without the mark")

    draw.text((tx, ty), title, font=title_font, fill=(247, 249, 250))

    gw = draw.textbbox((0, 0), tagline, font=tag_font)
    gx = (W - (gw[2] - gw[0])) // 2 - gw[0]
    draw.text((gx, ty + 260), tagline, font=tag_font, fill=(150, 160, 168))

    image.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes, {image.size[0]}x{image.size[1]})")


if __name__ == "__main__":
    main()
