from __future__ import annotations

import importlib
import math
from pathlib import Path
from typing import Any, Final

PUBLICATION_FONT_FAMILIES: Final = (
    "Pretendard",
    "Noto Sans CJK KR",
    "Malgun Gothic",
    "AppleGothic",
    "DejaVu Sans",
)


class PublicationRendererUnavailableError(RuntimeError):
    dependency: str

    def __init__(self, dependency: str) -> None:
        self.dependency = dependency
        super().__init__(f"Publication rendering requires the optional {dependency} dependency.")


class EmptyPublicationSeriesError(ValueError):
    def __init__(self) -> None:
        super().__init__("The selected result series has no finite samples.")


def publication_renderer_status() -> dict[str, Any]:
    try:
        importlib.import_module("matplotlib")
        importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        dependency = (exc.name or "matplotlib/numpy").partition(".")[0]
        return {
            "enabled": False,
            "reason": str(PublicationRendererUnavailableError(dependency)),
            "reason_code": "renderer_missing",
            "reason_params": {"dependency": dependency},
        }
    except (ImportError, OSError, RuntimeError) as exc:
        return {
            "enabled": False,
            "reason": f"Publication renderer could not initialize ({type(exc).__name__}).",
            "reason_code": "renderer_failed",
        }
    return {
        "enabled": True,
        "reason": "Matplotlib publication renderer is available with portable styling.",
        "reason_code": "renderer_ready",
    }


def interpret_series(time: list[float], values: list[float]) -> dict[str, Any]:
    pairs = [
        (float(t), float(v))
        for t, v in zip(time, values, strict=False)
        if math.isfinite(float(t)) and math.isfinite(float(v))
    ]
    if not pairs:
        raise EmptyPublicationSeriesError
    times, data = zip(*pairs)
    minimum = min(data)
    maximum = max(data)
    initial = data[0]
    final = data[-1]
    span = maximum - minimum
    delta = final - initial
    tolerance = max(abs(initial), abs(final), span, 1.0) * 1e-3
    direction = "stable" if abs(delta) <= tolerance else "increasing" if delta > 0 else "decreasing"
    peak_index = data.index(maximum)
    return {
        "scope": "descriptive",
        "samples": len(data),
        "start_time": times[0],
        "end_time": times[-1],
        "minimum": minimum,
        "maximum": maximum,
        "mean": sum(data) / len(data),
        "initial": initial,
        "final": final,
        "delta": delta,
        "percent_change": (delta / abs(initial) * 100) if initial else None,
        "peak_time": times[peak_index],
        "direction": direction,
    }


def _time_axis_label(time_unit: str | None) -> str:
    return f"Time ({time_unit})" if time_unit else "Time"


def _file_stem(text: str) -> str:
    return "_".join(part for part in text.replace("/", "_").split() if part)


def _with_unit(label: str, unit: str | None) -> str:
    return f"{label} ({unit})" if unit else label


def render_publication_series(series: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    return _render_line(
        series["time"],
        series["values"],
        x_label=_time_axis_label(series.get("time_unit")),
        y_label=_with_unit(series["variable"], series.get("unit")),
        legend_text=series.get("position"),
        stem=_file_stem(f"{series['variable']}_{series.get('position') or 'series'}"),
        out_dir=out_dir,
    )


def render_publication_profile(profile: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """One variable along one branch at one time; the legend names the branch and the time."""
    time = profile.get("timestep")
    when = "" if time is None else f", t = {float(time):.1f} {profile.get('timestep_unit') or 's'}"
    stem = f"{profile['branch']}_{profile['variable']}" + ("" if time is None else f"_t{float(time):08.1f}")
    return _render_line(
        profile["positions"],
        profile["values"],
        x_label="Position (m)",
        y_label=_with_unit(profile["variable"], profile.get("unit")),
        legend_text=f"{profile['branch']}{when}",
        keep_gaps=True,
        stem=_file_stem(stem),
        out_dir=out_dir,
    )


def _render_line(
    x_values: list[float],
    y_values: list[float],
    *,
    x_label: str,
    y_label: str,
    legend_text: str | None,
    stem: str,
    out_dir: Path,
    keep_gaps: bool = False,
) -> dict[str, Any]:
    try:
        import matplotlib
        import numpy as np
        matplotlib.use("Agg", force=True)
        from matplotlib import font_manager
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:
        dependency = (exc.name or "matplotlib/numpy").partition(".")[0]
        raise PublicationRendererUnavailableError(dependency) from exc
    except (ImportError, OSError, RuntimeError) as exc:
        raise PublicationRendererUnavailableError("matplotlib/numpy") from exc

    font_family = ""
    font_path = ""
    for candidate in PUBLICATION_FONT_FAMILIES:
        properties = font_manager.FontProperties(family=[candidate])
        try:
            font_path = font_manager.findfont(properties, fallback_to_default=False)
        except ValueError:
            continue
        font_family = candidate
        break
    if not font_path:
        properties = font_manager.FontProperties(family=["sans-serif"])
        font_path = font_manager.findfont(properties, fallback_to_default=True)
        font_family = font_manager.FontProperties(fname=font_path).get_name()

    time = np.asarray(x_values, dtype=float)
    values = np.asarray(y_values, dtype=float)
    finite = np.isfinite(time) & np.isfinite(values)
    line_x, line_y = time, np.where(finite, values, np.nan)
    time = time[finite]
    values = values[finite]
    if time.size == 0:
        raise EmptyPublicationSeriesError
    if not keep_gaps:
        line_x, line_y = time, values

    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{stem}.png"
    pdf = out_dir / f"{stem}.pdf"

    style = {
        "font.family": [font_family],
        "font.size": 9.0,
        "axes.labelsize": 9.0,
        "axes.linewidth": 0.8,
        "axes.unicode_minus": False,
        "xtick.labelsize": 8.0,
        "ytick.labelsize": 8.0,
        "xtick.major.width": 0.8,
        "ytick.major.width": 0.8,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
    with matplotlib.rc_context(style):
        fig, ax = plt.subplots(figsize=(7.2, 4.4), constrained_layout=True)
        try:
            # A point alone between two gaps has no line to show it, so a broken line also gets markers.
            marker = "o" if keep_gaps and not finite.all() else None
            ax.plot(
                line_x, line_y, color="#0072B2", linewidth=1.6, marker=marker, markersize=3, label=legend_text or None
            )
            ax.set_xlabel(x_label)
            ax.set_ylabel(y_label)
            ax.grid(False)

            xmin, xmax = float(time.min()), float(time.max())
            if xmin == xmax:
                xmin, xmax = xmin - 0.5, xmax + 0.5
            ymin, ymax = float(values.min()), float(values.max())
            pad = (ymax - ymin) * 0.06 if ymax != ymin else max(abs(ymin) * 0.06, 0.5)
            ax.set_xlim(xmin, xmax)
            ax.set_ylim(ymin - pad, ymax + pad)
            ax.set_xticks(np.linspace(xmin, xmax, 6))
            ax.set_yticks(np.linspace(ymin - pad, ymax + pad, 6))
            ax.ticklabel_format(useOffset=False)
            ax.minorticks_on()
            ax.tick_params(which="both", direction="in", top=True, right=True)
            if legend_text:
                legend = ax.legend(loc="best", frameon=True, edgecolor="black", framealpha=1)
                legend.get_frame().set_linewidth(0.8)

            fig.savefig(png, dpi=600, facecolor="white", transparent=False)
            fig.savefig(pdf, facecolor="white", transparent=False)
        finally:
            plt.close(fig)

    return {
        "png": str(png),
        "pdf": str(pdf),
        "dpi": 600,
        "font_family": font_family,
        "font_path": font_path,
        "style_source": "olga_companion.publication_plot",
    }
