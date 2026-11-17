"""
genkey_parser.py — Parser for OLGA .genkey simulation input files.

Usage:
    python genkey_parser.py <file.genkey>

Outputs parsed structure as JSON to stdout.
"""

import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Value parsing
# ---------------------------------------------------------------------------

# Keywords that map to booleans
_BOOL_MAP = {
    "ON": True, "OFF": False,
    "YES": True, "NO": False,
    "TRUE": True, "FALSE": False,
}

# Unit tokens: one or more non-space, non-comma, non-paren characters
# that start with a letter (not a digit or sign), used to detect units.
_UNIT_RE = re.compile(
    r"^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s+([A-Za-z][^\s,)=]*)$"
)


def parse_value(value_str: str):
    """Parse a single value token from a .genkey file.

    Handles:
      - Quoted strings          → str
      - Tuples (v1, v2, ...)    → list (each element recursively parsed)
      - ON/OFF/YES/NO           → bool
      - Plain integers          → int
      - Plain floats            → float
      - Number + unit           → {"value": <num>, "unit": "<unit>"}
      - Bare identifiers        → str
    """
    s = value_str.strip()

    # Quoted string
    if (s.startswith('"') and s.endswith('"')) or \
       (s.startswith("'") and s.endswith("'")):
        return s[1:-1]

    # Parenthesised tuple — plain "(v1, v2)" or with trailing unit "(v1, v2) ft"
    if s.startswith("("):
        # Find the matching closing paren
        depth = 0
        close = -1
        in_q = None
        for idx, ch in enumerate(s):
            if in_q:
                if ch == in_q:
                    in_q = None
            else:
                if ch in ('"', "'"):
                    in_q = ch
                elif ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0:
                        close = idx
                        break
        if close != -1:
            inner = s[1:close]
            elements = _split_respecting_quotes(inner)
            parsed_list = [parse_value(e.strip()) for e in elements]
            remainder = s[close + 1:].strip()
            if remainder:
                # remainder is a unit token like "ft", "m", "s", "kg/s"
                return {"value": parsed_list, "unit": remainder}
            return parsed_list

    # Boolean keywords (case-insensitive)
    upper = s.upper()
    if upper in _BOOL_MAP:
        return _BOOL_MAP[upper]

    # Number possibly followed by a unit
    m = _UNIT_RE.match(s)
    if m:
        raw_num, unit = m.group(1), m.group(2)
        num = _parse_number(raw_num)
        return {"value": num, "unit": unit}

    # Plain number
    num = _try_parse_number(s)
    if num is not None:
        return num

    # Bare identifier / unquoted string
    return s


def _parse_number(s: str):
    """Parse string as int or float; raises ValueError on failure."""
    try:
        iv = int(s)
        # Guard against "1.0" being parsed as int via float comparison
        if str(iv) == s:
            return iv
        return float(s)
    except ValueError:
        return float(s)


def _try_parse_number(s: str):
    """Return int/float or None."""
    try:
        return _parse_number(s)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Key-value pair parsing
# ---------------------------------------------------------------------------

def parse_key_value_pairs(line: str) -> dict:
    """Parse 'KEY1=VAL1, KEY2=VAL2 ...' from a parameter string.

    Values may be:
      - plain tokens (no spaces) until the next comma
      - quoted strings (may contain commas)
      - parenthesised tuples (may contain commas and nested quotes)
      - a number-unit pair like '48 h'

    Returns an ordered dict of {KEY: parsed_value}.
    """
    result = {}
    i = 0
    n = len(line)

    while i < n:
        # Skip leading whitespace and commas
        while i < n and line[i] in (' ', '\t', ','):
            i += 1
        if i >= n:
            break

        # Read KEY (up to '=')
        eq = line.find('=', i)
        if eq == -1:
            break
        key = line[i:eq].strip()
        i = eq + 1

        # Skip whitespace after '='
        while i < n and line[i] in (' ', '\t'):
            i += 1
        if i >= n:
            result[key] = None
            break

        # Read VALUE — may be: quoted, parenthesised, or bare (possibly with a unit)
        value_str, i = _read_value_token(line, i)
        result[key] = parse_value(value_str)

    return result


def _read_value_token(line: str, start: int) -> tuple:
    """Extract a value token from `line` starting at `start`.

    Returns (token_string, new_index).
    """
    n = len(line)
    i = start

    if i >= n:
        return ("", i)

    ch = line[i]

    # Quoted string
    if ch in ('"', "'"):
        quote = ch
        i += 1
        j = i
        while j < n:
            if line[j] == '\\':
                j += 2
                continue
            if line[j] == quote:
                break
            j += 1
        token = line[start:j + 1]
        return (token, j + 1)

    # Parenthesised tuple
    if ch == '(':
        depth = 0
        j = i
        in_quote = None
        while j < n:
            c = line[j]
            if in_quote:
                if c == '\\':
                    j += 2
                    continue
                if c == in_quote:
                    in_quote = None
            else:
                if c in ('"', "'"):
                    in_quote = c
                elif c == '(':
                    depth += 1
                elif c == ')':
                    depth -= 1
                    if depth == 0:
                        token = line[i:j + 1]
                        j += 1
                        # Check for a unit after the closing paren: ") ft"
                        # Consume optional whitespace, then a unit token if present
                        k = j
                        while k < n and line[k] == ' ':
                            k += 1
                        # Unit: starts with a letter, no '=' or ',' follows immediately
                        unit_start = k
                        while k < n and line[k] not in (',', '=', ' ', '\t'):
                            k += 1
                        potential_unit = line[unit_start:k]
                        if potential_unit and potential_unit[0].isalpha():
                            # Make sure we're not consuming a KEY= token
                            kk = k
                            while kk < n and line[kk] in (' ', '\t'):
                                kk += 1
                            if kk < n and line[kk] == '=':
                                # It's the next KEY= not a unit
                                pass
                            else:
                                token = token + ' ' + potential_unit
                                j = k
                        return (token, j)
            j += 1
        # Unmatched paren — return what we have
        return (line[i:], n)

    # Bare token — read until comma or end, but a single space may introduce a unit
    # Strategy: scan to the next ',' (outside quotes/parens), then check if the
    # token contains an embedded space indicating a number-unit pair.
    j = i
    in_quote = None
    depth = 0
    while j < n:
        c = line[j]
        if in_quote:
            if c == '\\':
                j += 2
                continue
            if c == in_quote:
                in_quote = None
        else:
            if c in ('"', "'"):
                in_quote = c
            elif c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            elif c == ',' and depth == 0:
                break
        j += 1

    token = line[i:j].rstrip()

    # If the bare token contains a space it might be "number unit" — keep as-is,
    # parse_value() will handle it via _UNIT_RE.
    # But if it's "number unit, KEY=..." we may have consumed too much or too little.
    # The scan above stops at comma so this is fine.

    return (token, j)


def _split_respecting_quotes(s: str) -> list:
    """Split string on commas, respecting quoted strings and nested parens."""
    parts = []
    depth = 0
    in_quote = None
    current = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if in_quote:
            current.append(c)
            if c == '\\' and i + 1 < n:
                i += 1
                current.append(s[i])
            elif c == in_quote:
                in_quote = None
        else:
            if c in ('"', "'"):
                in_quote = c
                current.append(c)
            elif c == '(':
                depth += 1
                current.append(c)
            elif c == ')':
                depth -= 1
                current.append(c)
            elif c == ',' and depth == 0:
                parts.append(''.join(current))
                current = []
            else:
                current.append(c)
        i += 1
    if current:
        parts.append(''.join(current))
    return parts


# ---------------------------------------------------------------------------
# Line pre-processing
# ---------------------------------------------------------------------------

def _preprocess_lines(raw_lines: list) -> list:
    """Merge continuation lines (trailing backslash) into logical lines.

    Returns list of (logical_line, original_line_indices) tuples.
    """
    logical = []
    i = 0
    n = len(raw_lines)
    while i < n:
        raw = raw_lines[i]
        # Strip trailing newline/CR
        stripped = raw.rstrip('\r\n')
        indices = [i]
        # Merge continuation lines
        while stripped.endswith('\\'):
            stripped = stripped[:-1]  # drop backslash
            i += 1
            if i < n:
                next_line = raw_lines[i].rstrip('\r\n').lstrip()
                stripped = stripped + next_line
                indices.append(i)
            else:
                break
        logical.append((stripped, indices))
        i += 1
    return logical


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

class GenkeyParser:
    """Parse an OLGA .genkey simulation input file.

    Attributes
    ----------
    filepath : str
        Absolute path to the parsed file.
    global_keywords : dict
        Top-level singleton keywords (OPTIONS, CASE, FILES, INTEGRATION, …).
        Keywords that appear multiple times are stored as lists under
        ``extra_keywords[keyword]``.
    materials : list[dict]
        All MATERIAL keyword entries.
    walls : list[dict]
        All WALL keyword entries.
    flowpaths : list[dict]
        NETWORKCOMPONENT TYPE=FLOWPATH blocks.  Each entry has keys:
        ``tag``, ``type``, ``header_params`` (dict), and ``children``
        (list of dicts with ``keyword`` and ``params``).
    nodes : list[dict]
        NETWORKCOMPONENT TYPE=NODE blocks (same structure as flowpaths).
    network_components : list[dict]
        All NETWORKCOMPONENT blocks (flowpaths + nodes + any other types).
    connections : list[dict]
        CONNECTION entries.
    comments : list[str]
        Comment lines (stripped of leading '!').
    raw_lines : list[str]
        Original file lines for round-trip editing.
    """

    # Keywords that are stored as lists (can appear multiple times)
    _LIST_KEYWORDS = {
        "MATERIAL", "WALL", "CONNECTION", "TRENDDATA", "PROFILEDATA",
        "OUTPUTDATA", "FORCHHEIMER", "LINEAR", "DELIVERABILITY",
        "PIPE", "VALVE", "POSITION", "HEATTRANSFER", "RESERVOIRCONTACT",
        "BRANCH", "GEOMETRY", "PARAMETERS",
    }

    # Keywords that go into dedicated top-level lists
    _DEDICATED = {"MATERIAL", "WALL", "CONNECTION"}

    def __init__(self, filepath: str):
        self.filepath = str(filepath)
        self.global_keywords: dict = {}
        self.extra_keywords: dict = {}   # overflow for repeated singletons
        self.materials: list = []
        self.walls: list = []
        self.flowpaths: list = []
        self.nodes: list = []
        self.network_components: list = []
        self.connections: list = []
        self.comments: list = []
        self.raw_lines: list = []

        self._parse()

    # ------------------------------------------------------------------
    # Parsing entry point
    # ------------------------------------------------------------------

    def _parse(self):
        with open(self.filepath, 'r', encoding='utf-8', errors='replace') as fh:
            self.raw_lines = fh.readlines()

        logical_lines = _preprocess_lines(self.raw_lines)

        # State for NETWORKCOMPONENT blocks
        in_network = False
        current_nc: dict = {}

        for logical_line, _indices in logical_lines:
            line = logical_line.strip()

            # Empty line
            if not line:
                continue

            # Comment
            if line.startswith('!'):
                self.comments.append(line[1:].strip())
                continue

            # ENDCASE
            if line.upper() == 'ENDCASE':
                break

            # ENDNETWORKCOMPONENT
            if line.upper() == 'ENDNETWORKCOMPONENT':
                if in_network:
                    self._finalise_network_component(current_nc)
                    in_network = False
                    current_nc = {}
                continue

            # Nested keyword (starts with a space in original — but after
            # continuation-joining the logical_line is stripped above, so
            # we need to check the *original* first physical line).
            # We detect nesting by checking whether the *first physical line*
            # of this logical group starts with a space.
            first_physical = self.raw_lines[_indices[0]].rstrip('\r\n')
            is_nested = first_physical and first_physical[0] == ' '

            if in_network and is_nested:
                self._handle_nested_keyword(line, current_nc)
                continue

            # Top-level or NETWORKCOMPONENT header
            keyword, rest = self._split_keyword(line)

            if keyword == 'NETWORKCOMPONENT':
                in_network = True
                params = parse_key_value_pairs(rest)
                current_nc = {
                    'type': params.get('TYPE', ''),
                    'tag': params.get('TAG', ''),
                    'header_params': params,
                    'children': [],
                }
                continue

            # Regular top-level keyword
            self._handle_top_level(keyword, rest)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _split_keyword(self, line: str) -> tuple:
        """Split 'KEYWORD rest...' → ('KEYWORD', 'rest...')."""
        parts = line.split(None, 1)
        if len(parts) == 1:
            return (parts[0].upper(), '')
        return (parts[0].upper(), parts[1])

    def _handle_top_level(self, keyword: str, rest: str):
        params = parse_key_value_pairs(rest) if rest else {}

        if keyword == 'MATERIAL':
            self.materials.append(params)
        elif keyword == 'WALL':
            self.walls.append(params)
        elif keyword == 'CONNECTION':
            self.connections.append(self._parse_connection(rest))
        else:
            # Store in global_keywords; if repeated, push to extra_keywords list
            if keyword not in self.global_keywords:
                self.global_keywords[keyword] = params
            else:
                if keyword not in self.extra_keywords:
                    self.extra_keywords[keyword] = [self.global_keywords[keyword]]
                self.extra_keywords[keyword].append(params)

    def _handle_nested_keyword(self, line: str, nc: dict):
        keyword, rest = self._split_keyword(line)
        params = parse_key_value_pairs(rest) if rest else {}
        nc['children'].append({'keyword': keyword, 'params': params})

    def _finalise_network_component(self, nc: dict):
        self.network_components.append(nc)
        nc_type = nc.get('type', '').upper()
        if nc_type == 'FLOWPATH':
            self.flowpaths.append(nc)
        elif 'NODE' in nc_type:
            # NODE and node-like network components (e.g. JUNCTIONNODE in OLGA2024
            # models) are all nodes for reference/topology purposes. Matching only
            # TYPE=NODE made every JUNCTIONNODE reference look "undefined" — a mass
            # false-positive on real cases that actually run in OLGA.
            self.nodes.append(nc)

    def _parse_connection(self, rest: str) -> dict:
        """Parse CONNECTION TERMINALS = (NODE_1 FLOWTERM_1, FLOWPATH_1 INLET)."""
        # Try to extract terminal list
        m = re.search(r'TERMINALS\s*=\s*\(([^)]*)\)', rest, re.IGNORECASE)
        if m:
            inner = m.group(1).strip()
            terminals = []
            for part in inner.split(','):
                tokens = part.strip().split()
                if len(tokens) >= 2:
                    terminals.append({'component': tokens[0], 'terminal': tokens[1]})
                elif tokens:
                    terminals.append({'component': tokens[0], 'terminal': ''})
            return {'TERMINALS': terminals}
        # Fallback: parse as generic key-value
        return parse_key_value_pairs(rest)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Export entire parsed structure as a JSON-serialisable plain dict."""
        return {
            'filepath': self.filepath,
            'global_keywords': self.global_keywords,
            'extra_keywords': self.extra_keywords,
            'materials': self.materials,
            'walls': self.walls,
            'flowpaths': self.flowpaths,
            'nodes': self.nodes,
            'network_components': self.network_components,
            'connections': self.connections,
            'comments': self.comments,
        }

    def to_json(self, indent: int = 2) -> str:
        """Export parsed structure as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

USAGE = "Usage: python genkey_parser.py <file.genkey> [--json] [--compact]"

# `--json` is accepted and is a no-op: this CLI has only ever emitted JSON, and
# callers have long passed the flag to say so. Flags are validated rather than
# ignored, because silently swallowing an unknown flag is how `--json` went
# unnoticed while the output stayed pretty-printed.
KNOWN_FLAGS = {"--json", "--compact"}


def main():
    if len(sys.argv) < 2:
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    flags = sys.argv[2:]
    unknown = [flag for flag in flags if flag not in KNOWN_FLAGS]
    if unknown:
        print(f"Error: unknown option(s): {' '.join(unknown)}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(2)

    if not Path(filepath).exists():
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    parser = GenkeyParser(filepath)
    if "--compact" in flags:
        # Machine consumers read this with json.loads. On a 420 KB case the
        # indentation alone is 1.4 MB -- more than half the payload -- which is
        # enough on its own to overrun the caller's output budget.
        print(json.dumps(parser.to_dict(), separators=(",", ":"), ensure_ascii=False))
    else:
        print(parser.to_json())


if __name__ == '__main__':
    main()
