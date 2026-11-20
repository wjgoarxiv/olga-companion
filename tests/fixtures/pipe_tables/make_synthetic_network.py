"""Write the synthetic pipe tables used by the import tests.

Every value is made up. The large table has the size and shape of a real engine-room
purge job: a supply main and a return main with eleven units between them, each unit
holding two parallel bundles (one inlet split into four arms, a mixing chamber, a split
into six arms, a merge), a vent branch and scheduled valves.

Run from the repository root: `python tests/fixtures/pipe_tables/make_synthetic_network.py`.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The documented template is a copy of the small branch; the generator writes
# it so the template always comes from the generator, never from a hand edit.
TEMPLATE_CSV = HERE.parent.parent.parent / "docs" / "examples" / "pipe_table_template.csv"
COLUMNS = (
    "flowpath", "pipe", "from_node", "to_node", "length_m", "elevation_m", "inner_diameter_m",
    "roughness_m", "valve", "valve_position", "valve_diameter_m", "valve_schedule",
    "node", "node_kind", "pressure_bar", "temperature_c", "gas_fraction", "water_fraction",
)
ROUGHNESS = 5e-05
UNITS = 11


class Table:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []
        self.valves = 0

    def flowpath(self, name: str, start: str, end: str, pipes: list[tuple[float, float, float]],
                 valve: tuple[float, float, str] | None = None) -> None:
        for index, (length, elevation, diameter) in enumerate(pipes, start=1):
            row: dict[str, object] = {
                "flowpath": name, "pipe": f"{name}_P{index}", "from_node": start, "to_node": end,
                "length_m": length, "elevation_m": elevation, "inner_diameter_m": diameter,
                "roughness_m": ROUGHNESS,
            }
            if valve is not None and index == 1:
                position, valve_diameter, schedule = valve
                self.valves += 1
                row.update(valve=f"V_{name}", valve_position=position,
                           valve_diameter_m=valve_diameter, valve_schedule=schedule)
            self.rows.append(row)

    def node(self, name: str, kind: str, pressure_bar: float) -> None:
        self.rows.append({
            "node": name, "node_kind": kind, "pressure_bar": pressure_bar,
            "temperature_c": 25.0, "gas_fraction": 1.0 if kind == "source" else 0.5, "water_fraction": 0.0,
        })

    def text(self) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(self.rows)
        return buffer.getvalue()


def _schedule(close_at: int) -> str:
    return f"0:1, {close_at - 1}:1, {close_at}:0"


_BUNDLE_IN = [(0.40, -0.10, 0.025), (0.25, 0.0, 0.025)]
_BUNDLE_OUT = [(0.30, 0.05, 0.025)]


def _bundle(table: Table, unit: int, stage: str) -> tuple[str, str]:
    """Arms between a 1->4 split, a mixing chamber and a 6->1 merge; returns (inlet, outlet)."""
    split_a, merge_a = f"U{unit}{stage}_SA", f"U{unit}{stage}_MA"
    split_b, merge_b = f"U{unit}{stage}_SB", f"U{unit}{stage}_MB"
    for arm in range(1, 5):
        table.flowpath(f"U{unit}{stage}_A{arm}", split_a, merge_a, [(0.06, -0.02, 0.008), (0.05, 0.0, 0.008)])
    table.flowpath(f"U{unit}{stage}_CH", merge_a, split_b, [(0.07, 0.0, 0.07)])
    for arm in range(1, 7):
        table.flowpath(f"U{unit}{stage}_B{arm}", split_b, merge_b, [(0.04, 0.0, 0.008), (0.03, 0.01, 0.008)])
    return split_a, merge_b


def large_network() -> Table:
    table = Table()
    table.node("SRC", "source", 15.0)
    table.node("OUT", "sink", 1.0)
    for unit in range(1, UNITS + 1):
        after = f"S_{unit}"
        if unit == 1:
            table.flowpath("SUPPLY", "SRC", after, [(12.0, 0.0, 0.05), (3.0, 1.5, 0.05), (2.0, 0.0, 0.05)],
                           valve=(0.5, 0.05, _schedule(300)))
        else:
            table.flowpath(f"MAIN_{unit}", f"S_{unit - 1}", after, [(0.5, 0.0, 0.05), (2.0, 0.0, 0.05), (1.5, 0.0, 0.05)],
                           valve=(0.3, 0.05, _schedule(300 + unit)))
        x_in, x_out = _bundle(table, unit, "X")
        y_in, y_out = _bundle(table, unit, "Y")
        table.flowpath(f"U{unit}_FEED", after, x_in, [(1.2, -0.8, 0.03), *_BUNDLE_IN], valve=(0.5, 0.03, _schedule(310 + unit)))
        table.flowpath(f"U{unit}_LINK", x_out, y_in, [*_BUNDLE_OUT, (0.8, 0.2, 0.025), *_BUNDLE_IN],
                       valve=(0.5, 0.025, _schedule(320 + unit)))
        table.flowpath(f"U{unit}_OUT", y_out, f"U{unit}_V", _BUNDLE_OUT)
        table.flowpath(f"U{unit}_VENT", f"U{unit}_V", f"VENT_{unit}", [(2.5, 2.0, 0.015)], valve=(0.5, 0.015, _schedule(330 + unit)))
        table.node(f"VENT_{unit}", "sink", 1.0)
        table.flowpath(f"U{unit}_RET", f"U{unit}_V", f"R_{unit}", [(1.0, 0.6, 0.03)], valve=(0.5, 0.03, _schedule(340 + unit)))
        to = f"R_{unit + 1}" if unit < UNITS else "OUT"
        table.flowpath(f"RET_{unit}", f"R_{unit}", to, [(1.5, 0.0, 0.05), (2.0, 0.0, 0.05)],
                       valve=(0.5, 0.05, _schedule(350 + unit)))
    return table


def small_branch() -> Table:
    table = Table()
    table.node("SRC", "source", 2.4)
    table.node("OUT_A", "sink", 2.0)
    table.node("OUT_B", "sink", 2.0)
    table.flowpath("FP_IN", "SRC", "J_1", [(20.0, 0.0, 0.05), (5.0, 2.0, 0.05)])
    table.flowpath("FP_A", "J_1", "OUT_A", [(10.0, 0.0, 0.04)], valve=(0.5, 0.04, _schedule(300)))
    table.flowpath("FP_B", "J_1", "OUT_B", [(8.0, -1.0, 0.04)])
    return table


def main() -> None:
    (HERE / "synthetic_network.csv").write_text(large_network().text(), encoding="utf-8", newline="")
    branch = small_branch().text()
    (HERE / "small_branch.csv").write_text(branch, encoding="utf-8", newline="")
    TEMPLATE_CSV.write_text(branch, encoding="utf-8", newline="")


if __name__ == "__main__":
    main()
