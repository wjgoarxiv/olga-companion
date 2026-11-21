"""Self-contained publication-quality matplotlib style for OLGA toolkit plots.

Mirrors the scientific-visualization skill's defaults (inward ticks, no grid,
TrueType-embedded fonts, DPI >= 600, Pretendard/Arial font stack) without
depending on that skill being installed, so the bundled sidecar stays
self-contained. Call ``apply_style()`` before creating any figure and
``save_figure()`` to export.
"""
from __future__ import annotations


_PREFERRED_FONTS = ["Pretendard", "Pretendard Variable", "Arial", "Helvetica",
                    "DejaVu Sans"]


def apply_style() -> None:
    """Apply the publication rcParams. Safe to call repeatedly."""
    import matplotlib as mpl
    from matplotlib import font_manager

    available = {f.name for f in font_manager.fontManager.ttflist}
    fonts = [f for f in _PREFERRED_FONTS if f in available] or ["DejaVu Sans"]

    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": fonts + mpl.rcParamsDefault["font.sans-serif"],
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
        "axes.grid": False,
        "axes.spines.top": True,
        "axes.spines.right": True,
        "axes.linewidth": 0.8,
        "axes.titlesize": 11,
        "axes.labelsize": 11,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.minor.visible": True,
        "ytick.minor.visible": True,
        "xtick.color": "black",
        "ytick.color": "black",
        "legend.frameon": True,
        "legend.edgecolor": "black",
        "legend.framealpha": 1.0,
        "figure.dpi": 120,
        "savefig.dpi": 600,
        "savefig.bbox": "tight",
        "lines.linewidth": 1.6,
    })


# Okabe-Ito colorblind-safe palette.
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7",
           "#E69F00", "#56B4E9", "#F0E442", "#000000"]


def save_figure(fig, path, *, dpi: int = 600, transparent: bool = True) -> str:
    """Save at publication DPI with a tight bounding box."""
    fig.savefig(path, dpi=dpi, bbox_inches="tight", transparent=transparent)
    return str(path)
