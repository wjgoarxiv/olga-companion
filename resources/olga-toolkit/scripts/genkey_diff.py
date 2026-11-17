"""
genkey_diff.py — Structural diff tool for OLGA .genkey simulation input files.

Usage:
    python genkey_diff.py <file_a.genkey> <file_b.genkey>

Outputs a human-readable diff report to stdout.
"""

import json
import sys
from pathlib import Path

from genkey_parser import GenkeyParser


# ---------------------------------------------------------------------------
# Value formatting helpers
# ---------------------------------------------------------------------------

def _fmt_value(v) -> str:
    """Format a parsed value back to a readable string."""
    if isinstance(v, dict) and "value" in v and "unit" in v:
        inner = v["value"]
        if isinstance(inner, list):
            inner_str = "(" + ", ".join(_fmt_value(x) for x in inner) + ")"
        else:
            inner_str = str(inner)
        return f"{inner_str} {v['unit']}"
    if isinstance(v, list):
        return "(" + ", ".join(_fmt_value(x) for x in v) + ")"
    if isinstance(v, bool):
        return "ON" if v else "OFF"
    return str(v)


def _values_equal(a, b) -> bool:
    """Deep equality check for parsed values."""
    if type(a) != type(b):
        # Allow int/float comparison
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return float(a) == float(b)
        return False
    if isinstance(a, dict):
        return a == b
    if isinstance(a, list):
        if len(a) != len(b):
            return False
        return all(_values_equal(x, y) for x, y in zip(a, b))
    return a == b


# ---------------------------------------------------------------------------
# Core diff helpers
# ---------------------------------------------------------------------------

def _diff_params(params_a: dict, params_b: dict) -> list:
    """Return list of {key, a, b} for keys that differ or are added/removed."""
    changes = []
    all_keys = list(params_a.keys()) + [k for k in params_b if k not in params_a]
    seen = set()
    for key in all_keys:
        if key in seen:
            continue
        seen.add(key)
        in_a = key in params_a
        in_b = key in params_b
        if in_a and in_b:
            va, vb = params_a[key], params_b[key]
            if not _values_equal(va, vb):
                changes.append({"key": key, "a": _fmt_value(va), "b": _fmt_value(vb)})
        elif in_a and not in_b:
            changes.append({"key": key, "a": _fmt_value(params_a[key]), "b": None})
        else:
            changes.append({"key": key, "a": None, "b": _fmt_value(params_b[key])})
    return changes


def _diff_labeled_list(list_a: list, list_b: list, label_key: str) -> dict:
    """Diff two lists of dicts keyed by label_key.

    Returns {"added": [...], "removed": [...], "modified": [...], "unchanged": [...]}
    """
    map_a = {item.get(label_key, ""): item for item in list_a}
    map_b = {item.get(label_key, ""): item for item in list_b}

    added = [map_b[k] for k in map_b if k not in map_a]
    removed = [map_a[k] for k in map_a if k not in map_b]
    modified = []
    unchanged = []

    for key in map_a:
        if key not in map_b:
            continue
        changes = _diff_params(map_a[key], map_b[key])
        if changes:
            modified.append({"label": key, "changes": changes})
        else:
            unchanged.append(key)

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged": unchanged,
    }


# ---------------------------------------------------------------------------
# GenkeyDiff
# ---------------------------------------------------------------------------

class GenkeyDiff:
    """Compare two .genkey files and produce a structural diff."""

    def __init__(self, file_a: str, file_b: str):
        self.file_a = str(file_a)
        self.file_b = str(file_b)
        self._pa = GenkeyParser(file_a)
        self._pb = GenkeyParser(file_b)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def diff(self) -> dict:
        """Compute and return the structural diff as a plain dict."""
        result = {
            "summary": {"added": 0, "removed": 0, "modified": 0, "unchanged": 0},
            "global_keywords": self._diff_global_keywords(),
            "materials": self._diff_materials(),
            "walls": self._diff_walls(),
            "flowpaths": self._diff_flowpaths(),
            "nodes": self._diff_nodes(),
            "connections": self._diff_connections(),
        }

        # Roll up summary counts
        s = result["summary"]
        for section_key in ("global_keywords", "materials", "walls", "flowpaths",
                            "nodes", "connections"):
            sec = result[section_key]
            s["added"] += len(sec.get("added", []))
            s["removed"] += len(sec.get("removed", []))
            s["modified"] += len(sec.get("modified", []))
            # connections uses unchanged_count (int); others use unchanged (list)
            unch = sec.get("unchanged_count", None)
            if unch is None:
                unch = len(sec.get("unchanged", []))
            s["unchanged"] += unch

        return result

    def report(self) -> str:
        """Return a human-readable diff report string."""
        d = self.diff()
        name_a = Path(self.file_a).name
        name_b = Path(self.file_b).name
        s = d["summary"]

        lines = []
        lines.append("=" * 55)
        lines.append(f"  Case Comparison: {name_a} vs {name_b}")
        lines.append("=" * 55)
        lines.append("")

        parts = []
        if s["modified"]:
            parts.append(f"{s['modified']} modified")
        if s["added"]:
            parts.append(f"{s['added']} added")
        if s["removed"]:
            parts.append(f"{s['removed']} removed")
        if not parts:
            parts.append("no differences")
        lines.append("Summary: " + ", ".join(parts))

        # --- Modified ---
        modified_lines = []
        gk = d["global_keywords"]
        for item in gk.get("modified", []):
            kw = item["keyword"]
            key = item["key"]
            modified_lines.append(f"  {kw}.{key}: {item['a']} → {item['b']}")

        for mat in d["materials"].get("modified", []):
            for ch in mat["changes"]:
                a_str = ch['a'] if ch['a'] is not None else "(absent)"
                b_str = ch['b'] if ch['b'] is not None else "(absent)"
                modified_lines.append(
                    f"  MATERIAL \"{mat['label']}\".{ch['key']}: {a_str} → {b_str}"
                )

        for wall in d["walls"].get("modified", []):
            for ch in wall["changes"]:
                a_str = ch['a'] if ch['a'] is not None else "(absent)"
                b_str = ch['b'] if ch['b'] is not None else "(absent)"
                modified_lines.append(
                    f"  WALL \"{wall['label']}\".{ch['key']}: {a_str} → {b_str}"
                )

        for fp in d["flowpaths"].get("modified", []):
            fp_label = fp["label"]
            for hc in fp.get("header_changes", []):
                a_str = hc['a'] if hc['a'] is not None else "(absent)"
                b_str = hc['b'] if hc['b'] is not None else "(absent)"
                modified_lines.append(
                    f"  FLOWPATH \"{fp_label}\".{hc['key']}: {a_str} → {b_str}"
                )
            for pc in fp.get("pipe_changes", []):
                a_str = pc['a'] if pc['a'] is not None else "(absent)"
                b_str = pc['b'] if pc['b'] is not None else "(absent)"
                modified_lines.append(
                    f"  PIPE \"{pc['pipe']}\".{pc['key']}: {a_str} → {b_str}"
                )
            for cc in fp.get("child_changes", []):
                a_str = cc['a'] if cc['a'] is not None else "(absent)"
                b_str = cc['b'] if cc['b'] is not None else "(absent)"
                kw_label = cc.get("label", "")
                label_part = f" \"{kw_label}\"" if kw_label else ""
                modified_lines.append(
                    f"  FLOWPATH \"{fp_label}\" > {cc['keyword']}{label_part}.{cc['key']}: {a_str} → {b_str}"
                )

        for nd in d["nodes"].get("modified", []):
            for ch in nd["changes"]:
                a_str = ch['a'] if ch['a'] is not None else "(absent)"
                b_str = ch['b'] if ch['b'] is not None else "(absent)"
                modified_lines.append(
                    f"  NODE \"{nd['label']}\".{ch['key']}: {a_str} → {b_str}"
                )

        if modified_lines:
            lines.append("")
            lines.append("Modified Parameters")
            lines.append("-" * 36)
            lines.extend(modified_lines)

        # --- Added ---
        added_lines = []
        for item in gk.get("added", []):
            added_lines.append(f"  KEYWORD \"{item['keyword']}\"")

        for mat in d["materials"].get("added", []):
            label = mat.get("LABEL", "?")
            mtype = mat.get("TYPE", "")
            phase = mat.get("PHASE", "")
            detail = ", ".join(x for x in [mtype, phase] if x)
            added_lines.append(f"  MATERIAL \"{label}\" ({detail})" if detail else f"  MATERIAL \"{label}\"")

        for wall in d["walls"].get("added", []):
            label = wall.get("LABEL", "?")
            added_lines.append(f"  WALL \"{label}\"")

        for fp in d["flowpaths"].get("added", []):
            tag = fp.get("tag", fp.get("header_params", {}).get("TAG", "?"))
            added_lines.append(f"  FLOWPATH \"{tag}\"")

        for nd in d["nodes"].get("added", []):
            tag = nd.get("tag", nd.get("header_params", {}).get("TAG", "?"))
            added_lines.append(f"  NODE \"{tag}\"")

        for conn in d["connections"].get("added", []):
            terminals = conn.get("TERMINALS", [])
            t_str = ", ".join(
                f"{t.get('component', '')} {t.get('terminal', '')}".strip()
                for t in terminals
            ) if terminals else str(conn)
            added_lines.append(f"  CONNECTION ({t_str})")

        if added_lines:
            lines.append("")
            lines.append("Added")
            lines.append("-" * 36)
            lines.extend(added_lines)

        # --- Removed ---
        removed_lines = []
        for item in gk.get("removed", []):
            removed_lines.append(f"  KEYWORD \"{item['keyword']}\"")

        for mat in d["materials"].get("removed", []):
            label = mat.get("LABEL", "?")
            removed_lines.append(f"  MATERIAL \"{label}\"")

        for wall in d["walls"].get("removed", []):
            label = wall.get("LABEL", "?")
            removed_lines.append(f"  WALL \"{label}\"")

        for fp in d["flowpaths"].get("removed", []):
            tag = fp.get("tag", fp.get("header_params", {}).get("TAG", "?"))
            removed_lines.append(f"  FLOWPATH \"{tag}\"")

        for nd in d["nodes"].get("removed", []):
            tag = nd.get("tag", nd.get("header_params", {}).get("TAG", "?"))
            removed_lines.append(f"  NODE \"{tag}\"")

        for conn in d["connections"].get("removed", []):
            terminals = conn.get("TERMINALS", [])
            t_str = ", ".join(
                f"{t.get('component', '')} {t.get('terminal', '')}".strip()
                for t in terminals
            ) if terminals else str(conn)
            removed_lines.append(f"  CONNECTION ({t_str})")

        if removed_lines:
            lines.append("")
            lines.append("Removed")
            lines.append("-" * 36)
            lines.extend(removed_lines)

        if not modified_lines and not added_lines and not removed_lines:
            lines.append("")
            lines.append("  Files are identical.")

        lines.append("")
        return "\n".join(lines)

    def to_json(self) -> str:
        """Export the diff result as a JSON string."""
        return json.dumps(self.diff(), indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Section diffing
    # ------------------------------------------------------------------

    def _diff_global_keywords(self) -> dict:
        """Diff top-level singleton keywords across both files.

        For keywords that appear multiple times (extra_keywords), match by LABEL
        if present, otherwise by position.
        """
        kw_a = self._pa.global_keywords
        kw_b = self._pb.global_keywords

        added = []    # {keyword, params} in B but not A
        removed = []  # {keyword, params} in A but not B
        modified = [] # {keyword, key, a, b}
        unchanged = []

        all_keys = list(kw_a.keys()) + [k for k in kw_b if k not in kw_a]
        seen = set()
        for kw in all_keys:
            if kw in seen:
                continue
            seen.add(kw)
            in_a = kw in kw_a
            in_b = kw in kw_b
            if in_a and in_b:
                changes = _diff_params(kw_a[kw], kw_b[kw])
                for ch in changes:
                    modified.append({
                        "keyword": kw,
                        "key": ch["key"],
                        "a": ch["a"],
                        "b": ch["b"],
                    })
                if not changes:
                    unchanged.append(kw)
            elif in_a:
                removed.append({"keyword": kw, "params": kw_a[kw]})
            else:
                added.append({"keyword": kw, "params": kw_b[kw]})

        # Also handle extra_keywords (repeated)
        extra_a = self._pa.extra_keywords
        extra_b = self._pb.extra_keywords
        all_extra = set(list(extra_a.keys()) + list(extra_b.keys()))
        for kw in all_extra:
            lst_a = extra_a.get(kw, [])
            lst_b = extra_b.get(kw, [])
            extra_result = self._diff_repeated_keyword(kw, lst_a, lst_b)
            modified.extend(extra_result["modified"])
            added.extend(extra_result["added"])
            removed.extend(extra_result["removed"])

        return {
            "modified": modified,
            "added": added,
            "removed": removed,
            "unchanged": unchanged,
        }

    def _diff_repeated_keyword(self, keyword: str, lst_a: list, lst_b: list) -> dict:
        """Diff repeated keyword instances, matching by LABEL when available."""
        # Try label-based matching first
        has_labels_a = all("LABEL" in item for item in lst_a)
        has_labels_b = all("LABEL" in item for item in lst_b)

        if has_labels_a and has_labels_b:
            map_a = {item["LABEL"]: item for item in lst_a}
            map_b = {item["LABEL"]: item for item in lst_b}
            modified = []
            added = []
            removed = []
            for label, params in map_b.items():
                if label not in map_a:
                    added.append({"keyword": keyword, "params": params})
                else:
                    changes = _diff_params(map_a[label], params)
                    for ch in changes:
                        modified.append({
                            "keyword": f"{keyword}[{label}]",
                            "key": ch["key"],
                            "a": ch["a"],
                            "b": ch["b"],
                        })
            for label in map_a:
                if label not in map_b:
                    removed.append({"keyword": keyword, "params": map_a[label]})
            return {"modified": modified, "added": added, "removed": removed}
        else:
            # Positional matching
            modified = []
            added = []
            removed = []
            for i, params_b in enumerate(lst_b):
                if i < len(lst_a):
                    changes = _diff_params(lst_a[i], params_b)
                    for ch in changes:
                        modified.append({
                            "keyword": f"{keyword}[{i}]",
                            "key": ch["key"],
                            "a": ch["a"],
                            "b": ch["b"],
                        })
                else:
                    added.append({"keyword": keyword, "params": params_b})
            for i in range(len(lst_b), len(lst_a)):
                removed.append({"keyword": keyword, "params": lst_a[i]})
            return {"modified": modified, "added": added, "removed": removed}

    def _diff_materials(self) -> dict:
        """Diff MATERIAL entries matched by LABEL."""
        result = _diff_labeled_list(self._pa.materials, self._pb.materials, "LABEL")
        return {
            "added": result["added"],
            "removed": result["removed"],
            "modified": result["modified"],
            "unchanged": result["unchanged"],
        }

    def _diff_walls(self) -> dict:
        """Diff WALL entries matched by LABEL."""
        result = _diff_labeled_list(self._pa.walls, self._pb.walls, "LABEL")
        return {
            "added": result["added"],
            "removed": result["removed"],
            "modified": result["modified"],
            "unchanged": result["unchanged"],
        }

    def _diff_flowpaths(self) -> dict:
        """Diff FLOWPATH network components matched by TAG.

        Within each flowpath, pipes are matched by their LABEL among PIPE children.
        Other child keywords are matched by (keyword, LABEL) pairs.
        """
        map_a = {fp.get("tag", ""): fp for fp in self._pa.flowpaths}
        map_b = {fp.get("tag", ""): fp for fp in self._pb.flowpaths}

        added = [fp for tag, fp in map_b.items() if tag not in map_a]
        removed = [fp for tag, fp in map_a.items() if tag not in map_b]
        modified = []
        unchanged = []

        for tag in map_a:
            if tag not in map_b:
                continue
            fp_a = map_a[tag]
            fp_b = map_b[tag]

            entry = {"label": tag, "header_changes": [], "pipe_changes": [], "child_changes": []}

            # Header params diff
            header_changes = _diff_params(fp_a.get("header_params", {}),
                                          fp_b.get("header_params", {}))
            entry["header_changes"] = [
                {"key": ch["key"], "a": ch["a"], "b": ch["b"]}
                for ch in header_changes
            ]

            # Children diff
            children_a = fp_a.get("children", [])
            children_b = fp_b.get("children", [])
            pipe_changes, child_changes = self._diff_flowpath_children(children_a, children_b)
            entry["pipe_changes"] = pipe_changes
            entry["child_changes"] = child_changes

            if entry["header_changes"] or entry["pipe_changes"] or entry["child_changes"]:
                modified.append(entry)
            else:
                unchanged.append(tag)

        return {
            "added": added,
            "removed": removed,
            "modified": modified,
            "unchanged": unchanged,
        }

    def _diff_flowpath_children(self, children_a: list, children_b: list) -> tuple:
        """Diff children of a flowpath. Returns (pipe_changes, other_child_changes)."""
        pipe_changes = []
        child_changes = []

        def extract_by_kw(children, kw):
            return [c for c in children if c.get("keyword", "").upper() == kw]

        # Diff PIPE children matched by LABEL
        pipes_a = extract_by_kw(children_a, "PIPE")
        pipes_b = extract_by_kw(children_b, "PIPE")
        pipe_map_a = {p["params"].get("LABEL", f"__pos_{i}"): p["params"]
                      for i, p in enumerate(pipes_a)}
        pipe_map_b = {p["params"].get("LABEL", f"__pos_{i}"): p["params"]
                      for i, p in enumerate(pipes_b)}

        for pipe_label in pipe_map_a:
            if pipe_label not in pipe_map_b:
                # Pipe removed — report as child change
                for key, val in pipe_map_a[pipe_label].items():
                    if key != "LABEL":
                        child_changes.append({
                            "keyword": "PIPE",
                            "label": pipe_label,
                            "key": key,
                            "a": _fmt_value(val),
                            "b": None,
                        })
                continue
            changes = _diff_params(pipe_map_a[pipe_label], pipe_map_b[pipe_label])
            for ch in changes:
                pipe_changes.append({
                    "pipe": pipe_label,
                    "key": ch["key"],
                    "a": ch["a"],
                    "b": ch["b"],
                })

        for pipe_label in pipe_map_b:
            if pipe_label not in pipe_map_a:
                for key, val in pipe_map_b[pipe_label].items():
                    if key != "LABEL":
                        child_changes.append({
                            "keyword": "PIPE",
                            "label": pipe_label,
                            "key": key,
                            "a": None,
                            "b": _fmt_value(val),
                        })

        # Diff non-PIPE children — group by (keyword, LABEL-if-present)
        def child_key(c):
            kw = c.get("keyword", "")
            label = c.get("params", {}).get("LABEL", "")
            return (kw, label)

        non_pipe_a = [c for c in children_a if c.get("keyword", "").upper() != "PIPE"]
        non_pipe_b = [c for c in children_b if c.get("keyword", "").upper() != "PIPE"]

        map_np_a = {}
        for c in non_pipe_a:
            k = child_key(c)
            map_np_a.setdefault(k, []).append(c["params"])

        map_np_b = {}
        for c in non_pipe_b:
            k = child_key(c)
            map_np_b.setdefault(k, []).append(c["params"])

        all_ck = set(list(map_np_a.keys()) + list(map_np_b.keys()))
        for ck in all_ck:
            lst_a = map_np_a.get(ck, [])
            lst_b = map_np_b.get(ck, [])
            kw_name, label = ck
            for i, pb in enumerate(lst_b):
                if i < len(lst_a):
                    changes = _diff_params(lst_a[i], pb)
                    for ch in changes:
                        child_changes.append({
                            "keyword": kw_name,
                            "label": label,
                            "key": ch["key"],
                            "a": ch["a"],
                            "b": ch["b"],
                        })
                else:
                    for key, val in pb.items():
                        child_changes.append({
                            "keyword": kw_name,
                            "label": label,
                            "key": key,
                            "a": None,
                            "b": _fmt_value(val),
                        })
            for i in range(len(lst_b), len(lst_a)):
                for key, val in lst_a[i].items():
                    child_changes.append({
                        "keyword": kw_name,
                        "label": label,
                        "key": key,
                        "a": _fmt_value(val),
                        "b": None,
                    })

        return pipe_changes, child_changes

    def _diff_nodes(self) -> dict:
        """Diff NODE network components matched by TAG."""
        map_a = {nd.get("tag", ""): nd for nd in self._pa.nodes}
        map_b = {nd.get("tag", ""): nd for nd in self._pb.nodes}

        added = [nd for tag, nd in map_b.items() if tag not in map_a]
        removed = [nd for tag, nd in map_a.items() if tag not in map_b]
        modified = []
        unchanged = []

        for tag in map_a:
            if tag not in map_b:
                continue
            nd_a = map_a[tag]
            nd_b = map_b[tag]
            changes = _diff_params(nd_a.get("header_params", {}),
                                   nd_b.get("header_params", {}))
            # Also diff children
            child_changes_flat = []
            _, child_changes = self._diff_flowpath_children(
                nd_a.get("children", []), nd_b.get("children", [])
            )
            for cc in child_changes:
                child_changes_flat.append({
                    "key": f"{cc['keyword']}.{cc['key']}",
                    "a": cc["a"],
                    "b": cc["b"],
                })

            all_changes = [{"key": ch["key"], "a": ch["a"], "b": ch["b"]}
                           for ch in changes] + child_changes_flat

            if all_changes:
                modified.append({"label": tag, "changes": all_changes})
            else:
                unchanged.append(tag)

        return {
            "added": added,
            "removed": removed,
            "modified": modified,
            "unchanged": unchanged,
        }

    def _diff_connections(self) -> dict:
        """Diff CONNECTION entries.

        Connections are matched by their terminal set (order-insensitive within
        the terminal list). If no match found, they're added/removed.
        """
        def conn_signature(conn) -> frozenset:
            terminals = conn.get("TERMINALS", [])
            if not terminals:
                return frozenset([str(conn)])
            return frozenset(
                f"{t.get('component', '')}:{t.get('terminal', '')}"
                for t in terminals
            )

        sigs_a = {conn_signature(c): c for c in self._pa.connections}
        sigs_b = {conn_signature(c): c for c in self._pb.connections}

        added = [c for sig, c in sigs_b.items() if sig not in sigs_a]
        removed = [c for sig, c in sigs_a.items() if sig not in sigs_b]
        unchanged_count = sum(1 for sig in sigs_a if sig in sigs_b)

        return {
            "added": added,
            "removed": removed,
            "unchanged_count": unchanged_count,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print("Usage: python genkey_diff.py <file_a.genkey> <file_b.genkey>",
              file=sys.stderr)
        sys.exit(1)

    file_a, file_b = sys.argv[1], sys.argv[2]
    for f in (file_a, file_b):
        if not Path(f).exists():
            print(f"Error: file not found: {f}", file=sys.stderr)
            sys.exit(1)

    differ = GenkeyDiff(file_a, file_b)
    print(differ.report())


if __name__ == "__main__":
    main()
