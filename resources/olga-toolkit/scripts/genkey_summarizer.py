"""
genkey_summarizer.py — Human-readable summary of a parsed OLGA .genkey file.

Usage:
    python genkey_summarizer.py <file.genkey>

Outputs a formatted text summary to stdout.
"""

import json
import sys
from pathlib import Path

from genkey_parser import GenkeyParser


# ---------------------------------------------------------------------------
# Helpers for extracting typed values from parsed dicts
# ---------------------------------------------------------------------------

def _val(v) -> str:
    """Convert a parsed value (str/int/float/bool/dict/list) to a display string."""
    if v is None:
        return ""
    if isinstance(v, dict) and "value" in v and "unit" in v:
        val = v["value"]
        unit = v["unit"]
        if isinstance(val, list):
            inner = ", ".join(str(_num(x)) for x in val)
            return f"({inner}) {unit}"
        return f"{_num(val)} {unit}"
    if isinstance(v, list):
        return ", ".join(_val(x) for x in v)
    if isinstance(v, bool):
        return "ON" if v else "OFF"
    if isinstance(v, float):
        return _num(v)
    return str(v)


def _num(v) -> str:
    """Format a number: ints stay as ints, floats drop trailing zeros."""
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        formatted = f"{v:g}"
        return formatted
    return str(v)


def _scalar(v) -> float | None:
    """Extract the numeric part of a value (strips units)."""
    if v is None:
        return None
    if isinstance(v, dict) and "value" in v:
        inner = v["value"]
        if isinstance(inner, (int, float)):
            return float(inner)
        if isinstance(inner, list) and inner:
            return float(inner[0])
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _unit(v) -> str:
    """Extract the unit string from a parsed value."""
    if isinstance(v, dict) and "unit" in v:
        return v["unit"]
    return ""


def _get(params: dict, *keys, default=""):
    """Lookup any of the given keys (case-insensitive) from a params dict."""
    upper = {k.upper(): v for k, v in params.items()}
    for key in keys:
        result = upper.get(key.upper())
        if result is not None:
            return result
    return default


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

WIDE = 63  # total width of the separator line


def _hr(char="─", width=WIDE) -> str:
    return char * width


def _section(title: str) -> str:
    return f"\n  {title}\n  {_hr()}"


def _field(label: str, value: str, label_width: int = 14) -> str:
    if not value and value != 0:
        return ""
    return f"  {label:<{label_width}}{value}"


# ---------------------------------------------------------------------------
# GenkeySummarizer
# ---------------------------------------------------------------------------

class GenkeySummarizer:
    """Produce human-readable and machine-readable summaries of a .genkey file."""

    def __init__(self, parser: GenkeyParser):
        self.parser = parser

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def summarize(self) -> str:
        """Return a multi-section human-readable summary string."""
        parts = []
        parts.append(self._header())
        parts.append(self._case_info())
        parts.append(self._simulation_settings())
        parts.append(self._pvt_file())
        parts.append(self._materials_section())
        parts.append(self._walls_section())
        parts.append(self._topology_section())
        parts.append(self._flowpaths_section())
        parts.append(self._nodes_section())
        parts.append(self._equipment_section())
        parts.append(self._output_section())
        parts.append(f"\n{'═' * WIDE}\n")
        return "\n".join(p for p in parts if p)

    def to_dict(self) -> dict:
        """Return a JSON-serializable structured summary."""
        p = self.parser
        case = p.global_keywords.get("CASE", {})
        options = p.global_keywords.get("OPTIONS", {})
        integration = p.global_keywords.get("INTEGRATION", {})
        files = p.global_keywords.get("FILES", {})

        return {
            "case_info": {
                "title": _val(_get(case, "TITLE")),
                "author": _val(_get(case, "AUTHOR")),
                "project": _val(_get(case, "PROJECT")),
                "description": _val(_get(case, "DESCRIPTION")),
            },
            "pvt_file": _val(_get(files, "PVTFILE", "PVT")),
            "simulation": {
                "flow_model": _val(_get(options, "FLOWMODEL", "COMPOSITIONAL")),
                "steady_state": _val(_get(options, "STEADYSTATE")),
                "end_time": _val(_get(integration, "ENDTIME", "TEND")),
                "dtstart": _val(_get(integration, "DTSTART")),
                "mindt": _val(_get(integration, "MINDT")),
                "maxdt": _val(_get(integration, "MAXDT")),
            },
            "materials": [
                {
                    "name": _val(_get(m, "TAG", "LABEL", "NAME")),
                    "type": _val(_get(m, "TYPE", "PHASE")),
                    "conductivity": _val(_get(m, "CONDUCTIVITY", "THERMCOND")),
                    "capacity": _val(_get(m, "CAPACITY", "HEATCAPACITY")),
                }
                for m in p.materials
            ],
            "walls": [
                {
                    "name": _val(_get(w, "TAG", "LABEL", "NAME")),
                    "layers": len(_layer_list(_get(w, "MATERIAL", "LAYERS"))),
                    "thickness": _val(_get(w, "THICKNESS")),
                }
                for w in p.walls
            ],
            "topology": {
                "flowpath_count": len(p.flowpaths),
                "node_count": len(p.nodes),
                "connection_count": len(p.connections),
            },
            "flowpaths": [self._flowpath_dict(fp) for fp in p.flowpaths],
            "nodes": [self._node_dict(nd) for nd in p.nodes],
            "equipment": self._equipment_dict(),
            "output": self._output_dict(),
        }

    # ------------------------------------------------------------------
    # Summary sections
    # ------------------------------------------------------------------

    def _header(self) -> str:
        case = self.parser.global_keywords.get("CASE", {})
        title = _val(_get(case, "TITLE")) or Path(self.parser.filepath).stem
        bar = "═" * WIDE
        return f"{bar}\n  OLGA Case Summary: {title}\n{bar}"

    def _case_info(self) -> str:
        case = self.parser.global_keywords.get("CASE", {})
        lines = [_section("Case Information")]
        lines.append(_field("Title:", _val(_get(case, "TITLE"))))
        lines.append(_field("Author:", _val(_get(case, "AUTHOR"))))
        lines.append(_field("Project:", _val(_get(case, "PROJECT"))))
        desc = _val(_get(case, "DESCRIPTION"))
        if desc:
            lines.append(_field("Description:", desc))
        return "\n".join(l for l in lines if l)

    def _pvt_file(self) -> str:
        files = self.parser.global_keywords.get("FILES", {})
        pvt = _val(_get(files, "PVTFILE", "PVT"))
        if not pvt:
            return ""
        return _field("PVT File:", pvt)

    def _simulation_settings(self) -> str:
        options = self.parser.global_keywords.get("OPTIONS", {})
        integration = self.parser.global_keywords.get("INTEGRATION", {})

        lines = [_section("Simulation Settings")]

        flow_model = _val(_get(options, "FLOWMODEL", "COMPOSITIONAL"))
        lines.append(_field("Flow Model:", flow_model or "—"))

        steady = _get(options, "STEADYSTATE")
        if steady is not None:
            lines.append(_field("Steady State:", _val(steady)))

        end_time = _get(integration, "ENDTIME", "TEND")
        if end_time is not None:
            lines.append(_field("End Time:", _val(end_time)))

        # Time step summary on one line
        ts_parts = []
        for key, label in [("DTSTART", "DTSTART"), ("MINDT", "MINDT"), ("MAXDT", "MAXDT")]:
            v = _get(integration, key)
            if v is not None:
                ts_parts.append(f"{label}={_val(v)}")
        if ts_parts:
            lines.append(_field("Time Steps:", ", ".join(ts_parts)))

        return "\n".join(l for l in lines if l)

    def _materials_section(self) -> str:
        mats = self.parser.materials
        lines = [_section(f"Materials ({len(mats)})")]
        if not mats:
            lines.append("  (none)")
            return "\n".join(lines)

        col_w = 28
        lines.append(f"  {'Name':<{col_w}} Type")
        lines.append(f"  {_hr('·', col_w)}  {_hr('·', 20)}")
        for m in mats:
            name = _val(_get(m, "TAG", "LABEL", "NAME")) or "(unnamed)"
            mtype = _val(_get(m, "TYPE", "PHASE")) or "—"
            lines.append(f"  {name:<{col_w}} {mtype}")

        return "\n".join(lines)

    def _walls_section(self) -> str:
        walls = self.parser.walls
        lines = [_section(f"Walls ({len(walls)})")]
        if not walls:
            lines.append("  (none)")
            return "\n".join(lines)

        col_w = 28
        lines.append(f"  {'Name':<{col_w}} Layers")
        lines.append(f"  {_hr('·', col_w)}  {_hr('·', 10)}")
        for w in walls:
            name = _val(_get(w, "TAG", "LABEL", "NAME")) or "(unnamed)"
            layer_val = _get(w, "MATERIAL", "LAYERS", "LAYER")
            n_layers = len(_layer_list(layer_val)) if layer_val else "—"
            lines.append(f"  {name:<{col_w}} {n_layers}")

        return "\n".join(lines)

    def _topology_section(self) -> str:
        p = self.parser
        lines = [_section("Network Topology")]
        lines.append(_field("Flow Paths:", str(len(p.flowpaths))))
        lines.append(_field("Nodes:", str(len(p.nodes))))
        lines.append(_field("Connections:", str(len(p.connections))))

        if p.connections:
            lines.append("\n  Connections:")
            for conn in p.connections:
                terminals = conn.get("TERMINALS", [])
                if terminals:
                    parts = [f"{t.get('component','')} [{t.get('terminal','')}]"
                             for t in terminals]
                    lines.append(f"    {' ↔ '.join(parts)}")
        return "\n".join(l for l in lines if l)

    def _flowpaths_section(self) -> str:
        fps = self.parser.flowpaths
        if not fps:
            return ""

        lines = [_section(f"Flow Path Details ({len(fps)})")]
        for fp in fps:
            lines.append(self._format_flowpath(fp))

        return "\n".join(lines)

    def _format_flowpath(self, fp: dict) -> str:
        tag = fp.get("tag") or fp.get("header_params", {}).get("TAG") or "(unnamed)"
        children = fp.get("children", [])

        pipes = [c for c in children if c["keyword"] == "PIPE"]
        valves = [c for c in children if c["keyword"] == "VALVE"]
        positions = [c for c in children if c["keyword"] == "POSITION"]

        # Aggregate pipe stats
        total_length = 0.0
        length_unit = ""
        diameters = []
        wall_types = set()

        for pipe in pipes:
            params = pipe["params"]
            lseg = _get(params, "LSEGMENT", "LENGTH", "L")
            if lseg is not None:
                seg_len = _scalar(lseg)
                if seg_len is not None:
                    # LSEGMENT can be a list of segments
                    raw = lseg
                    if isinstance(raw, dict) and isinstance(raw.get("value"), list):
                        total_length += sum(
                            x if isinstance(x, (int, float)) else 0
                            for x in raw["value"]
                        )
                    elif isinstance(raw, list):
                        total_length += sum(
                            _scalar(x) or 0 for x in raw
                        )
                    else:
                        total_length += seg_len
                    if not length_unit:
                        length_unit = _unit(lseg)

            diam = _get(params, "DIAMETER", "D", "ID")
            if diam is not None:
                d_val = _scalar(diam)
                d_unit = _unit(diam)
                if d_val is not None:
                    diameters.append((d_val, d_unit))

            wall = _get(params, "WALL", "WALLTYPE")
            if wall:
                wall_types.add(_val(wall))

        lines = [f"\n  ┌─ {tag}"]
        lines.append(f"  │  Pipes: {len(pipes)}")

        if total_length:
            u = length_unit or ""
            lines.append(f"  │  Total Length: {_num(total_length)} {u}".rstrip())

        if diameters:
            vals = [d for d, _ in diameters]
            unit_str = diameters[0][1] if diameters else ""
            if len(set(vals)) == 1:
                lines.append(f"  │  Diameter: {_num(vals[0])} {unit_str}".rstrip())
            else:
                lines.append(
                    f"  │  Diameter: {_num(min(vals))}–{_num(max(vals))} {unit_str}".rstrip()
                )

        if wall_types:
            lines.append(f"  │  Wall Types: {', '.join(sorted(wall_types))}")

        if valves:
            for valve in valves:
                vp = valve["params"]
                v_label = _val(_get(vp, "TAG", "LABEL", "NAME")) or "valve"
                v_pos = _val(_get(vp, "OPENING", "POSITION", "STROKEFRACTION"))
                v_type = _val(_get(vp, "TYPE", "VALVETYPE"))
                parts = [v_label]
                if v_type:
                    parts.append(f"type={v_type}")
                if v_pos:
                    parts.append(f"opening={v_pos}")
                lines.append(f"  │  Valve: {', '.join(parts)}")

        if positions:
            lines.append(f"  │  Positions: {len(positions)}")

        lines.append("  └" + _hr("─", WIDE - 4))
        return "\n".join(lines)

    def _nodes_section(self) -> str:
        nodes = self.parser.nodes
        if not nodes:
            return ""

        lines = [_section(f"Node Details ({len(nodes)})")]

        col_w = 22
        lines.append(f"  {'Name':<{col_w}} {'Type':<16} Boundary Condition")
        lines.append(f"  {_hr('·', col_w)}  {_hr('·', 16)}  {_hr('·', 20)}")

        for nd in nodes:
            lines.append(self._format_node(nd))

        return "\n".join(lines)

    def _format_node(self, nd: dict) -> str:
        tag = nd.get("tag") or nd.get("header_params", {}).get("TAG") or "(unnamed)"
        hp = nd.get("header_params", {})
        children = nd.get("children", [])

        ntype = _val(_get(hp, "NODETYPE", "TYPE")) or "—"
        # TYPE is already consumed as the NETWORKCOMPONENT TYPE, so look in children
        for child in children:
            t = _val(_get(child["params"], "NODETYPE", "TYPE"))
            if t:
                ntype = t
                break

        # Boundary condition values
        bc_parts = []
        pressure = None
        for child in children:
            cp = child["params"]
            p = _get(cp, "PRESSURE", "P")
            t = _get(cp, "TEMPERATURE", "T", "TEMP")
            if p is not None:
                pressure = _val(p)
                bc_parts.append(f"P={pressure}")
            if t is not None:
                bc_parts.append(f"T={_val(t)}")

        col_w = 22
        bc = ", ".join(bc_parts) if bc_parts else "—"
        return f"  {tag:<{col_w}} {ntype:<16} {bc}"

    def _equipment_section(self) -> str:
        """Valves and other equipment across all flowpaths."""
        all_valves = []
        for fp in self.parser.flowpaths:
            fp_tag = fp.get("tag") or "(unnamed)"
            for child in fp.get("children", []):
                if child["keyword"] == "VALVE":
                    all_valves.append((fp_tag, child["params"]))

        if not all_valves:
            return ""

        lines = [_section(f"Equipment — Valves ({len(all_valves)})")]
        col_fp = 20
        col_tag = 20
        lines.append(f"  {'Flow Path':<{col_fp}} {'Tag':<{col_tag}} Type            Opening")
        lines.append(f"  {_hr('·', col_fp)}  {_hr('·', col_tag)}  {_hr('·', 16)}  {_hr('·', 10)}")

        for fp_tag, vp in all_valves:
            vtag = _val(_get(vp, "TAG", "LABEL", "NAME")) or "—"
            vtype = _val(_get(vp, "TYPE", "VALVETYPE")) or "—"
            vopening = _val(_get(vp, "OPENING", "STROKEFRACTION", "POSITION")) or "—"
            lines.append(f"  {fp_tag:<{col_fp}} {vtag:<{col_tag}} {vtype:<16}  {vopening}")

        return "\n".join(lines)

    def _output_section(self) -> str:
        p = self.parser

        # OUTPUTDATA / TRENDDATA / PROFILEDATA
        trend_entries = p.extra_keywords.get("TRENDDATA", [])
        if not trend_entries and "TRENDDATA" in p.global_keywords:
            trend_entries = [p.global_keywords["TRENDDATA"]]

        profile_entries = p.extra_keywords.get("PROFILEDATA", [])
        if not profile_entries and "PROFILEDATA" in p.global_keywords:
            profile_entries = [p.global_keywords["PROFILEDATA"]]

        output_entries = p.extra_keywords.get("OUTPUTDATA", [])
        if not output_entries and "OUTPUTDATA" in p.global_keywords:
            output_entries = [p.global_keywords["OUTPUTDATA"]]

        if not (trend_entries or profile_entries or output_entries):
            return ""

        lines = [_section("Output Configuration")]

        if trend_entries:
            lines.append(f"  Trend Data ({len(trend_entries)} group(s)):")
            for entry in trend_entries[:5]:  # cap display
                var = _val(_get(entry, "VARIABLE", "VARIABLES", "VAR"))
                dt = _val(_get(entry, "DTOUT", "INTERVAL", "DT"))
                parts = []
                if var:
                    parts.append(f"var={var}")
                if dt:
                    parts.append(f"dt={dt}")
                if parts:
                    lines.append(f"    {', '.join(parts)}")
            if len(trend_entries) > 5:
                lines.append(f"    ... and {len(trend_entries) - 5} more")

        if profile_entries:
            lines.append(f"  Profile Data ({len(profile_entries)} group(s)):")
            for entry in profile_entries[:5]:
                var = _val(_get(entry, "VARIABLE", "VARIABLES", "VAR"))
                dt = _val(_get(entry, "DTOUT", "INTERVAL", "DT"))
                parts = []
                if var:
                    parts.append(f"var={var}")
                if dt:
                    parts.append(f"dt={dt}")
                if parts:
                    lines.append(f"    {', '.join(parts)}")
            if len(profile_entries) > 5:
                lines.append(f"    ... and {len(profile_entries) - 5} more")

        if output_entries:
            lines.append(f"  Output Data ({len(output_entries)} group(s)):")
            for entry in output_entries[:3]:
                var = _val(_get(entry, "VARIABLE", "VARIABLES", "VAR"))
                dt = _val(_get(entry, "DTOUT", "INTERVAL", "DT"))
                parts = []
                if var:
                    parts.append(f"var={var}")
                if dt:
                    parts.append(f"dt={dt}")
                if parts:
                    lines.append(f"    {', '.join(parts)}")

        return "\n".join(l for l in lines if l)

    # ------------------------------------------------------------------
    # to_dict helpers
    # ------------------------------------------------------------------

    def _flowpath_dict(self, fp: dict) -> dict:
        tag = fp.get("tag") or fp.get("header_params", {}).get("TAG") or ""
        children = fp.get("children", [])
        pipes = [c for c in children if c["keyword"] == "PIPE"]
        valves = [c for c in children if c["keyword"] == "VALVE"]

        total_length = 0.0
        length_unit = ""
        diameters = []
        wall_types = set()

        for pipe in pipes:
            params = pipe["params"]
            lseg = _get(params, "LSEGMENT", "LENGTH", "L")
            if lseg is not None:
                if isinstance(lseg, dict) and isinstance(lseg.get("value"), list):
                    total_length += sum(
                        x if isinstance(x, (int, float)) else 0
                        for x in lseg["value"]
                    )
                elif isinstance(lseg, list):
                    total_length += sum(_scalar(x) or 0 for x in lseg)
                else:
                    total_length += _scalar(lseg) or 0
                if not length_unit:
                    length_unit = _unit(lseg)

            diam = _get(params, "DIAMETER", "D", "ID")
            if diam is not None:
                d_val = _scalar(diam)
                if d_val is not None:
                    diameters.append(d_val)

            wall = _get(params, "WALL", "WALLTYPE")
            if wall:
                wall_types.add(_val(wall))

        return {
            "name": tag,
            "pipe_count": len(pipes),
            "total_length": {"value": total_length, "unit": length_unit},
            "diameter_min": min(diameters) if diameters else None,
            "diameter_max": max(diameters) if diameters else None,
            "wall_types": sorted(wall_types),
            "valve_count": len(valves),
        }

    def _node_dict(self, nd: dict) -> dict:
        tag = nd.get("tag") or nd.get("header_params", {}).get("TAG") or ""
        children = nd.get("children", [])
        bc = {}
        for child in children:
            cp = child["params"]
            p = _get(cp, "PRESSURE", "P")
            t = _get(cp, "TEMPERATURE", "T", "TEMP")
            if p is not None:
                bc["pressure"] = _val(p)
            if t is not None:
                bc["temperature"] = _val(t)
        return {"name": tag, "boundary_conditions": bc}

    def _equipment_dict(self) -> dict:
        valves = []
        for fp in self.parser.flowpaths:
            fp_tag = fp.get("tag") or ""
            for child in fp.get("children", []):
                if child["keyword"] == "VALVE":
                    vp = child["params"]
                    valves.append({
                        "flowpath": fp_tag,
                        "tag": _val(_get(vp, "TAG", "LABEL", "NAME")),
                        "type": _val(_get(vp, "TYPE", "VALVETYPE")),
                        "opening": _val(_get(vp, "OPENING", "STROKEFRACTION", "POSITION")),
                    })
        return {"valves": valves}

    def _output_dict(self) -> dict:
        p = self.parser

        def _collect(keyword: str) -> list:
            entries = p.extra_keywords.get(keyword, [])
            if not entries and keyword in p.global_keywords:
                entries = [p.global_keywords[keyword]]
            return [
                {
                    "variable": _val(_get(e, "VARIABLE", "VARIABLES", "VAR")),
                    "dtout": _val(_get(e, "DTOUT", "INTERVAL", "DT")),
                }
                for e in entries
            ]

        return {
            "trend_data": _collect("TRENDDATA"),
            "profile_data": _collect("PROFILEDATA"),
            "output_data": _collect("OUTPUTDATA"),
        }


# ---------------------------------------------------------------------------
# Layer list helper (used for wall layer count)
# ---------------------------------------------------------------------------

def _layer_list(v) -> list:
    """Return a list from a parsed value that may be a single item or a list."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, dict) and isinstance(v.get("value"), list):
        return v["value"]
    return [v]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python genkey_summarizer.py <file.genkey> [--json]", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    if not Path(filepath).exists():
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    flag = sys.argv[2] if len(sys.argv) > 2 else ""

    # Ensure stdout handles Unicode box-drawing characters on all platforms
    # (Windows terminals may default to a narrow codepage like cp949).
    import io
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    elif sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    parser = GenkeyParser(filepath)
    summarizer = GenkeySummarizer(parser)

    if flag == "--json":
        print(json.dumps(summarizer.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(summarizer.summarize())


if __name__ == "__main__":
    main()
