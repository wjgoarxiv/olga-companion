"""
topology_visualizer.py — ASCII topology visualizer for OLGA .genkey files.

Usage:
    python topology_visualizer.py <file.genkey>

Outputs an ASCII diagram of the network topology to stdout.
"""

import sys
import io
from pathlib import Path
from genkey_parser import GenkeyParser


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _extract_value(val):
    """Get numeric/plain value from parser output.

    - dict with "value" key  -> return the value (recurse into lists)
    - list                   -> return list of extracted values
    - otherwise              -> return as-is
    """
    if isinstance(val, dict) and "value" in val:
        v = val["value"]
        if isinstance(v, list):
            return [_extract_value(x) for x in v]
        return v
    if isinstance(val, list):
        return [_extract_value(x) for x in val]
    return val


def _unit_of(val):
    """Extract unit string from a parser value dict."""
    if isinstance(val, dict):
        return val.get("unit", "")
    return ""


def _fmt_val(val):
    """Format a parsed value for display."""
    if val is None:
        return ""
    if isinstance(val, dict):
        v = _extract_value(val)
        u = val.get("unit", "")
        if isinstance(v, list):
            return f"({', '.join(str(x) for x in v)}) {u}".strip()
        return f"{v} {u}".strip() if u else str(v)
    if isinstance(val, list):
        extracted = [_extract_value(x) for x in val]
        return f"({', '.join(str(x) for x in extracted)})"
    return str(val)


def _sum_lsegment(raw) -> float:
    """Sum all segment lengths from a LSEGMENT value, converting ft->m."""
    if raw is None:
        return 0.0
    u = _unit_of(raw)
    vals = _extract_value(raw)
    if not isinstance(vals, list):
        vals = [vals]
    total = 0.0
    for v in vals:
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if u and u.lower() in ("ft", "feet"):
            fv *= 0.3048
        total += fv
    return total


# ---------------------------------------------------------------------------
# TopologyVisualizer
# ---------------------------------------------------------------------------

class TopologyVisualizer:
    """Build ASCII diagrams from a parsed GenkeyParser instance."""

    def __init__(self, parser: GenkeyParser):
        self.parser = parser
        self._fp_by_tag = {fp["tag"]: fp for fp in parser.flowpaths}
        self._node_by_tag = {nd["tag"]: nd for nd in parser.nodes}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def visualize(self) -> str:
        """Return an ASCII diagram of the network topology."""
        lines = []
        lines.append("Network Topology")
        lines.append("\u2550" * 16)
        lines.append("")

        if not self.parser.flowpaths:
            lines.append("(no flowpaths found)")
            return "\n".join(lines)

        fp_connections = self._build_fp_connections()

        for fp in self.parser.flowpaths:
            fp_tag = fp["tag"]
            conns = fp_connections.get(fp_tag, {})
            inlet_tag = conns.get("INLET")
            outlet_tag = conns.get("OUTLET")

            pipes = self._get_pipes(fp)
            pipe_count = len(pipes)
            total_length = self._total_length(pipes)
            diameters = self._diameter_range(pipes)
            valves = self._get_valves(fp)

            is_vertical = self._is_vertical(fp, inlet_tag, outlet_tag, pipes)

            if is_vertical:
                block = self._render_vertical(
                    fp_tag, inlet_tag, outlet_tag,
                    pipe_count, total_length, diameters, valves
                )
            else:
                block = self._render_horizontal(
                    fp_tag, inlet_tag, outlet_tag,
                    pipe_count, total_length, diameters, valves, pipes
                )

            lines.extend(block)
            lines.append("")

        return "\n".join(lines)

    def pipe_table(self) -> str:
        """Return a formatted table of all pipes for every flowpath."""
        out = []
        for fp in self.parser.flowpaths:
            fp_tag = fp["tag"]
            pipes = self._get_pipes(fp)

            title = f"Pipe Table: {fp_tag}"
            out.append(title)
            out.append("\u2550" * len(title))

            if not pipes:
                out.append("  (no pipes)")
                out.append("")
                continue

            col_w = [4, 44, 22, 9, 12, 14]
            header = (
                f"{'#':<{col_w[0]}}"
                f"{'Label':<{col_w[1]}}"
                f"{'Wall':<{col_w[2]}}"
                f"{'Segments':>{col_w[3]}}"
                f"{'Length(m)':>{col_w[4]}}"
                f"  {'Diameter':<{col_w[5]}}"
            )
            out.append(header)
            out.append("-" * (sum(col_w) + 2))

            for idx, pipe in enumerate(pipes, 1):
                p = pipe["params"]
                label = str(p.get("LABEL", p.get("TAG", f"Pipe_{idx}")))
                wall  = str(p.get("WALL", ""))
                nseg  = str(p.get("NSEGMENT", p.get("NSEGMENTS", p.get("NUMSECTIONS", ""))))
                length_m = self._total_length([pipe])
                length_str = f"{length_m:.1f}" if length_m else ""
                diameter = _fmt_val(p.get("DIAMETER", p.get("ID")))

                label_str = (label[:col_w[1]-1] + "\u2026") if len(label) > col_w[1]-1 else label
                wall_str  = (wall[:col_w[2]-1]  + "\u2026") if len(wall)  > col_w[2]-1  else wall

                row = (
                    f"{idx:<{col_w[0]}}"
                    f"{label_str:<{col_w[1]}}"
                    f"{wall_str:<{col_w[2]}}"
                    f"{nseg:>{col_w[3]}}"
                    f"{length_str:>{col_w[4]}}"
                    f"  {diameter:<{col_w[5]}}"
                )
                out.append(row)

            out.append("")

        return "\n".join(out)

    # ------------------------------------------------------------------
    # Connection parsing
    # ------------------------------------------------------------------

    def _build_fp_connections(self) -> dict:
        """Return {flowpath_tag: {terminal: node_tag}} from CONNECTION entries."""
        fp_conns: dict = {}
        for conn in self.parser.connections:
            terminals = conn.get("TERMINALS", [])
            if len(terminals) < 2:
                continue
            fp_term = None
            node_tag = None
            for t in terminals:
                comp = t["component"]
                term = t["terminal"].upper()
                if comp in self._fp_by_tag:
                    fp_term = (comp, term)
                elif comp in self._node_by_tag:
                    node_tag = comp
            if fp_term and node_tag:
                fp_tag, side = fp_term
                fp_conns.setdefault(fp_tag, {})[side] = node_tag
        return fp_conns

    # ------------------------------------------------------------------
    # Flowpath introspection
    # ------------------------------------------------------------------

    def _get_pipes(self, fp: dict) -> list:
        return [c for c in fp.get("children", []) if c["keyword"] == "PIPE"]

    def _get_valves(self, fp: dict) -> list:
        return [c for c in fp.get("children", []) if c["keyword"] == "VALVE"]

    def _total_length(self, pipes: list) -> float:
        """Sum LSEGMENT lengths across all pipes, in metres."""
        total = 0.0
        for pipe in pipes:
            p = pipe["params"]
            # Prefer LSEGMENT (list of segment lengths); fall back to LENGTH
            raw = p.get("LSEGMENT", p.get("LENGTH"))
            total += _sum_lsegment(raw)
        return total

    def _diameter_range(self, pipes: list) -> str:
        """Return a human-readable diameter range string."""
        diams = []
        unit = ""
        for pipe in pipes:
            raw = pipe["params"].get("DIAMETER", pipe["params"].get("ID"))
            if raw is None:
                continue
            v = _extract_value(raw)
            u = _unit_of(raw)
            if u:
                unit = u
            vals = v if isinstance(v, list) else [v]
            for x in vals:
                try:
                    diams.append(float(x))
                except (TypeError, ValueError):
                    pass
        if not diams:
            return ""
        lo, hi = min(diams), max(diams)
        if abs(hi - lo) < 1e-9:
            return f"D={lo:.4g} {unit}".strip()
        return f"D={lo:.4g}-{hi:.4g} {unit}".strip()

    # ------------------------------------------------------------------
    # Layout detection
    # ------------------------------------------------------------------

    def _is_vertical(self, fp: dict, inlet_tag, outlet_tag, pipes: list) -> bool:
        """Heuristic: vertical layout for wells."""
        # CLOSED outlet node -> well bottomhole
        if outlet_tag and outlet_tag in self._node_by_tag:
            nd = self._node_by_tag[outlet_tag]
            nd_params = self._node_params(nd)
            if str(nd_params.get("TYPE", "")).upper() == "CLOSED":
                return True

        # Pipe labels contain depth markers
        for pipe in pipes[:3]:
            label = str(pipe["params"].get("LABEL", "")).upper()
            if "MD_FROM" in label or "TVD_FROM" in label or "_BH_" in label:
                return True

        # Flowpath tag hints
        fp_tag = fp["tag"].upper()
        if any(kw in fp_tag for kw in ("WELL", "TUBING", "TBG", "ANNUL", "CASING")):
            return True

        # Node tag hints
        for tag in (inlet_tag, outlet_tag):
            if tag and any(kw in tag.upper() for kw in ("_BH_", "BOTTOM", "MD_", "_TVD")):
                return True

        # Y variation across pipes (Y is the vertical axis; ZEND stays 0)
        y_vals = []
        for pipe in pipes:
            p = pipe["params"]
            for key in ("YEND", "Y", "ELEVATION"):
                raw = p.get(key)
                if raw is not None:
                    v = _extract_value(raw)
                    if isinstance(v, list):
                        for x in v:
                            try:
                                y_vals.append(float(x))
                            except (TypeError, ValueError):
                                pass
                    else:
                        try:
                            y_vals.append(float(v))
                        except (TypeError, ValueError):
                            pass
                    break

        if len(y_vals) >= 2 and (max(y_vals) - min(y_vals)) > 10:
            return True

        return False

    # ------------------------------------------------------------------
    # Node info helpers
    # ------------------------------------------------------------------

    def _node_params(self, nd: dict) -> dict:
        """Return the PARAMETERS child dict for a node, or empty dict."""
        for child in nd.get("children", []):
            if child["keyword"] == "PARAMETERS":
                return child["params"]
        return {}

    def _node_info_lines(self, node_tag: str) -> list:
        """Return display lines for a node (no borders)."""
        if not node_tag:
            return ["(unconnected)"]
        if node_tag not in self._node_by_tag:
            return [node_tag]

        nd = self._node_by_tag[node_tag]
        params = self._node_params(nd)

        label = str(params.get("LABEL", node_tag))
        nd_type = str(params.get("TYPE", nd["header_params"].get("TYPE", ""))).upper()

        info = [label, f"TYPE: {nd_type}"]

        pressure = params.get("PRESSURE", params.get("P"))
        temp     = params.get("TEMPERATURE", params.get("T"))
        parts = []
        if pressure is not None:
            parts.append(f"P={_fmt_val(pressure)}")
        if temp is not None:
            parts.append(f"T={_fmt_val(temp)}")
        if parts:
            info.append(", ".join(parts))

        return info

    def _make_box(self, lines: list, min_width: int = 23) -> list:
        """Wrap text lines in a Unicode box."""
        inner_w = max(min_width, max((len(l) for l in lines), default=0) + 2)
        top    = "\u250c" + "\u2500" * inner_w + "\u2510"
        bottom = "\u2514" + "\u2500" * inner_w + "\u2518"
        rows = [top]
        for line in lines:
            rows.append("\u2502 " + line.ljust(inner_w - 2) + " \u2502")
        rows.append(bottom)
        return rows

    def _box_width(self, box: list) -> int:
        return len(box[0]) if box else 0

    # ------------------------------------------------------------------
    # Vertical (well) renderer
    # ------------------------------------------------------------------

    def _render_vertical(self, fp_tag, inlet_tag, outlet_tag,
                          pipe_count, total_length, diameters, valves) -> list:
        out = []

        # Convention: wellhead (PRESSURE/non-CLOSED) at top, bottomhole (CLOSED) at bottom.
        # OLGA typically assigns INLET=bottomhole, OUTLET=wellhead for wells, so swap
        # when the inlet node type is CLOSED.
        top_tag, bot_tag = outlet_tag, inlet_tag
        inlet_nd = self._node_by_tag.get(inlet_tag) if inlet_tag else None
        if inlet_nd:
            inlet_type = self._node_params(inlet_nd).get("TYPE", "")
            if str(inlet_type).upper() != "CLOSED":
                # inlet is not bottomhole — keep natural order (inlet on top)
                top_tag, bot_tag = inlet_tag, outlet_tag

        top_box = self._make_box(self._node_info_lines(top_tag))
        box_w = self._box_width(top_box)
        mid = box_w // 2
        out.extend(top_box)

        # Build connector annotation lines
        pipe_s = "pipe" if pipe_count == 1 else "pipes"
        connector_lines = [
            f"{fp_tag} ({pipe_count} {pipe_s})",
            f"Total length: ~{total_length:.0f}m",
        ]
        if diameters:
            connector_lines.append(diameters)

        for valve in valves:
            vp = valve["params"]
            v_label = str(vp.get("LABEL", vp.get("TAG", "VALVE")))
            v_pipe  = vp.get("PIPE", "")
            ann = f"[VALVE: {v_label}"
            if v_pipe:
                # Show just the pipe tag/number, not the full label string
                pipe_str = _fmt_val(v_pipe)
                # Truncate long pipe labels to a short identifier
                if len(pipe_str) > 30:
                    pipe_str = pipe_str[:27] + "\u2026"
                ann += f" @ {pipe_str}"
            ann += "]"
            connector_lines.append(ann)

        for cl in connector_lines:
            out.append(" " * mid + "\u2502 " + cl)

        bot_box = self._make_box(self._node_info_lines(bot_tag), min_width=box_w - 2)
        bot_w = self._box_width(bot_box)
        offset = max(0, mid - bot_w // 2)
        if offset:
            bot_box = [" " * offset + row for row in bot_box]

        out.extend(bot_box)
        return out

    # ------------------------------------------------------------------
    # Horizontal (pipeline) renderer
    # ------------------------------------------------------------------

    def _render_horizontal(self, fp_tag, inlet_tag, outlet_tag,
                            pipe_count, total_length, diameters, valves, pipes) -> list:
        out = []

        inlet_box  = self._make_box(self._node_info_lines(inlet_tag))
        outlet_box = self._make_box(self._node_info_lines(outlet_tag))

        pipe_s = "pipe" if pipe_count == 1 else "pipes"
        fp_label = f" {fp_tag} ({pipe_count} {pipe_s}, {total_length:.0f}m) "

        # Extra annotation lines (below connector row)
        extra_parts = []
        for valve in valves:
            vp = valve["params"]
            v_label = str(vp.get("LABEL", vp.get("TAG", "VALVE")))
            v_pipe  = vp.get("PIPE", "")
            ann = f"[VALVE: {v_label}"
            if v_pipe:
                ann += f" @ Pipe_{_fmt_val(v_pipe)}"
            ann += "]"
            extra_parts.append(ann)
        if diameters:
            extra_parts.append(diameters)

        # Pad both boxes to same height
        total_h = max(len(inlet_box), len(outlet_box))
        while len(inlet_box) < total_h:
            inlet_box.append(" " * self._box_width(inlet_box))
        while len(outlet_box) < total_h:
            outlet_box.append(" " * self._box_width(outlet_box))

        mid_row = total_h // 2

        # Connector column width
        conn_content_w = max(len(fp_label), 10)
        arm = "\u2500" * 4  # ────

        for i in range(total_h):
            left  = inlet_box[i]
            right = outlet_box[i]
            if i == mid_row:
                middle = arm + fp_label.rstrip() + arm
                # Stitch: replace last char of left box border and first of right
                row = left[:-1] + middle + right[1:]
            else:
                pad = " " * (len(arm) * 2 + conn_content_w)
                row = left + pad + right
            out.append(row)

        # Pipe detail lines below the diagram
        if pipes:
            left_w = self._box_width(inlet_box)
            indent = " " * (left_w + len(arm))
            if len(pipes) <= 6:
                for j, pipe in enumerate(pipes):
                    p = pipe["params"]
                    label  = str(p.get("LABEL", f"Pipe_{j+1}"))
                    length_m = self._total_length([pipe])
                    diam   = _fmt_val(p.get("DIAMETER", p.get("ID")))
                    sym = "\u251c\u2500" if j < len(pipes) - 1 else "\u2514\u2500"
                    detail = f"{sym} {label}"
                    if length_m:
                        detail += f" ({length_m:.0f}m"
                        if diam:
                            detail += f", D={diam}"
                        detail += ")"
                    out.append(indent + detail)
            else:
                first_label = str(pipes[0]["params"].get("LABEL", "Pipe_1"))
                last_label  = str(pipes[-1]["params"].get("LABEL", f"Pipe_{len(pipes)}"))
                out.append(indent + f"\u251c\u2500 {first_label}")
                out.append(indent + f"\u2502  ... ({len(pipes)-2} more pipes) ...")
                out.append(indent + f"\u2514\u2500 {last_label}")

        # Extra annotations (valves, diameters)
        if extra_parts:
            left_w = self._box_width(inlet_box)
            indent = " " * (left_w + len(arm))
            for part in extra_parts:
                out.append(indent + part)

        return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    # Ensure UTF-8 output on Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    else:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    if len(sys.argv) < 2:
        print("Usage: python topology_visualizer.py <file.genkey>", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    if not Path(filepath).exists():
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    parser = GenkeyParser(filepath)
    viz = TopologyVisualizer(parser)

    print(viz.visualize())

    if parser.flowpaths:
        print()
        print(viz.pipe_table())


if __name__ == "__main__":
    main()
