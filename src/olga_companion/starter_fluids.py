"""The generic air-water PVT table that ships with the app.

It is a plain bundled file: this module only says where it is and what it is. The table was
computed once in Multiflash (CPA) from ``air_water_cpa.mfl``; nothing here computes a property.
"""

from __future__ import annotations

from pathlib import Path

from . import config

LABEL = "AIR_WATER"
MODEL = "CPA"
TABLE_NAME = "air_water_cpa.tab"
TEMPERATURE_RANGE_C = (0, 80)
PRESSURE_RANGE_BAR = (0.5, 20)
KIND_EN = "Generic air-water table (CPA, 0–80 °C, 0.5–20 bar). Not made for your case; check that it covers your conditions."
KIND_KO = "범용 공기-물 표 (CPA, 0–80 °C, 0.5–20 bar). 내 사례에 맞춘 표가 아니므로 운전 조건이 범위 안인지 확인하세요."


def bundled_table() -> Path:
    """The bundled table; it sits beside the toolkit folder in dev and packaged builds."""
    return config.toolkit_dir().parent / "fluids" / TABLE_NAME
