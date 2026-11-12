"""
genkey_writer.py — Line-based editor for OLGA .genkey simulation input files.

Works on raw lines from the file, preserving all comments, formatting, and
ordering. Only the specific KEY=VALUE pair requested is modified.

Usage (CLI):
    python genkey_writer.py <file.genkey> <KEYWORD> <KEY> <value> [--label LABEL]

Examples:
    python genkey_writer.py case.genkey INTEGRATION ENDTIME "96 h"
    python genkey_writer.py case.genkey PIPE DIAMETER "0.6 ft" --label Pipe_1
"""

import re
import sys
import argparse
from pathlib import Path

# Import parser from same directory
sys.path.insert(0, str(Path(__file__).parent))
from genkey_parser import GenkeyParser, _preprocess_lines


# ---------------------------------------------------------------------------
# Value formatting
# ---------------------------------------------------------------------------

def format_value(value) -> str:
    """Convert a Python value back to .genkey format.

    Rules:
      - bool          → ON / OFF
      - str           → quoted if it contains spaces, else plain
      - list          → (v1, v2, v3)
      - dict with     → value unit  or  (v1, v2) unit
        "value"/"unit"
      - int / float   → str(value)
    """
    if isinstance(value, bool):
        return "ON" if value else "OFF"

    if isinstance(value, str):
        # "number unit" patterns like "96 h", "0.6 m", or OLGA's
        # dimensionless "1 -" values are valid unquoted in .genkey.
        _num_unit_re = re.compile(
            r'^[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\s+(?:[A-Za-z][^\s,)=]*|-)$'
        )
        # Parenthesized OLGA tuples may contain commas and an optional trailing unit,
        # e.g. TIME=(0, 299, 300, 1200) s or OPENING=(1, 1, 0, 0). Do not quote
        # them; OLGA expects the tuple syntax as a native value, not a string.
        _tuple_re = re.compile(r'^\([^\n]*\)(?:\s+[A-Za-z][^\s,)=]*)?$')
        if _tuple_re.match(value.strip()):
            return value.strip()
        if ',' in value or '=' in value:
            escaped = value.replace('"', '\\"')
            return f'"{escaped}"'
        if ' ' in value and not _num_unit_re.match(value):
            escaped = value.replace('"', '\\"')
            return f'"{escaped}"'
        return value

    if isinstance(value, list):
        inner = ", ".join(format_value(v) for v in value)
        return f"({inner})"

    if isinstance(value, dict):
        v = value.get("value")
        unit = value.get("unit", "")
        formatted_v = format_value(v) if isinstance(v, list) else _format_scalar(v)
        if unit:
            return f"{formatted_v} {unit}"
        return formatted_v

    if isinstance(value, float):
        # Preserve reasonable precision without trailing zeros where possible
        s = f"{value:g}"
        return s

    # int, NoneType, anything else
    return str(value)


def _format_scalar(value) -> str:
    """Format a scalar (non-list, non-dict) value."""
    if isinstance(value, bool):
        return "ON" if value else "OFF"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


# ---------------------------------------------------------------------------
# Internal line-search helpers
# ---------------------------------------------------------------------------

# Regex to find KEY= in a line (case-insensitive)
def _key_pattern(key: str) -> re.Pattern:
    return re.compile(
        r'(?<![A-Za-z0-9_])' + re.escape(key) + r'\s*=',
        re.IGNORECASE,
    )


def _replace_value_in_text(text: str, key: str, new_value_str: str) -> tuple:
    """Replace the value of `key` in `text`.

    Returns (new_text, replaced: bool).

    Strategy: find KEY=, then locate the value token that follows and
    replace it with new_value_str, preserving surrounding text.
    """
    pat = _key_pattern(key)
    m = pat.search(text)
    if not m:
        return text, False

    # Position right after the '='
    pos = m.end()

    # Skip optional whitespace
    while pos < len(text) and text[pos] in (' ', '\t'):
        pos += 1

    if pos >= len(text):
        return text, False

    # Determine end of old value token
    old_end = _find_value_end(text, pos)

    new_text = text[:pos] + new_value_str + text[old_end:]
    return new_text, True


def _find_value_end(text: str, start: int) -> int:
    """Return the index one past the value token that begins at `start`."""
    n = len(text)
    i = start
    ch = text[i]

    # Quoted string
    if ch in ('"', "'"):
        quote = ch
        i += 1
        while i < n:
            if text[i] == '\\':
                i += 2
                continue
            if text[i] == quote:
                i += 1
                break
            i += 1
        return i

    # Parenthesised tuple (possibly with trailing unit)
    if ch == '(':
        depth = 0
        in_q = None
        while i < n:
            c = text[i]
            if in_q:
                if c == '\\':
                    i += 2
                    continue
                if c == in_q:
                    in_q = None
            else:
                if c in ('"', "'"):
                    in_q = c
                elif c == '(':
                    depth += 1
                elif c == ')':
                    depth -= 1
                    if depth == 0:
                        i += 1
                        # Consume optional trailing unit: " ft"
                        k = i
                        while k < n and text[k] == ' ':
                            k += 1
                        unit_start = k
                        while k < n and text[k] not in (',', '=', ' ', '\t'):
                            k += 1
                        potential_unit = text[unit_start:k]
                        if potential_unit and potential_unit[0].isalpha():
                            # Ensure it's not a KEY= token
                            kk = k
                            while kk < n and text[kk] in (' ', '\t'):
                                kk += 1
                            if kk >= n or text[kk] != '=':
                                i = k
                        return i
            i += 1
        return i

    # Bare token: read to next comma (outside quotes/parens), or end of text
    # A bare token may include a space-separated unit: "96 h"
    j = i
    in_q = None
    depth = 0
    while j < n:
        c = text[j]
        if in_q:
            if c == '\\':
                j += 2
                continue
            if c == in_q:
                in_q = None
        else:
            if c in ('"', "'"):
                in_q = c
            elif c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            elif c == ',' and depth == 0:
                break
        j += 1

    return j


def _get_label_from_text(text: str) -> str:
    """Extract the LABEL value from a line's text (case-insensitive)."""
    m = re.search(r'(?<![A-Za-z0-9_])LABEL\s*=\s*', text, re.IGNORECASE)
    if not m:
        return ""
    pos = m.end()
    while pos < len(text) and text[pos] in (' ', '\t'):
        pos += 1
    if pos >= len(text):
        return ""
    end = _find_value_end(text, pos)
    raw = text[pos:end].strip()
    # Strip quotes
    if (raw.startswith('"') and raw.endswith('"')) or \
       (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw


# ---------------------------------------------------------------------------
# Logical-block locator
# ---------------------------------------------------------------------------

class _LogicalBlock:
    """Represents a logical keyword block (possibly spanning continuation lines)."""

    def __init__(self, keyword: str, line_indices: list, merged_text: str):
        self.keyword = keyword          # e.g. "INTEGRATION"
        self.line_indices = line_indices  # original line numbers (0-based)
        self.merged_text = merged_text  # full logical text (continuations joined)

    @property
    def first_line(self) -> int:
        return self.line_indices[0]

    @property
    def last_line(self) -> int:
        return self.line_indices[-1]


def _build_logical_blocks(raw_lines: list) -> list:
    """Build list of _LogicalBlock from raw_lines.

    Only returns blocks that start with a keyword (not blank, not comment).
    """
    blocks = []
    i = 0
    n = len(raw_lines)
    while i < n:
        raw = raw_lines[i]
        stripped = raw.rstrip('\r\n')
        indices = [i]

        # Merge continuation lines
        while stripped.endswith('\\'):
            stripped = stripped[:-1]
            i += 1
            if i < n:
                next_line = raw_lines[i].rstrip('\r\n').lstrip()
                stripped = stripped + next_line
                indices.append(i)
            else:
                break

        logical = stripped.strip()
        if logical and not logical.startswith('!'):
            kw_match = re.match(r'([A-Za-z_][A-Za-z0-9_]*)', logical)
            if kw_match:
                kw = kw_match.group(1).upper()
                blocks.append(_LogicalBlock(kw, indices, logical))

        i += 1

    return blocks


# ---------------------------------------------------------------------------
# GenkeyWriter
# ---------------------------------------------------------------------------

class GenkeyWriter:
    """Line-based editor for .genkey files.

    Reads the file into raw_lines, finds the target line(s) by scanning
    logical blocks, modifies the specific KEY=VALUE in place, and writes
    back — preserving all comments, formatting, and ordering.
    """

    def __init__(self, filepath: str):
        self.filepath = str(filepath)
        self.parser = GenkeyParser(filepath)
        # Work on a mutable copy of raw lines
        self.raw_lines: list = list(self.parser.raw_lines)
        self._dirty = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_parameter(self, keyword: str, key: str, value,
                      label: str = None) -> bool:
        """Find the keyword block (optionally filtered by LABEL) and set KEY=value.

        Handles continuation lines: if the key appears on a continuation
        line rather than the header line, it will still be found.

        Returns True if found and modified, False if not found.
        """
        keyword_upper = keyword.upper()
        blocks = _build_logical_blocks(self.raw_lines)

        for block in blocks:
            if block.keyword != keyword_upper:
                continue

            # If label filter, check that this block matches
            if label is not None:
                block_label = _get_label_from_text(block.merged_text)
                if block_label.lower() != label.lower():
                    continue

            # Try to find the key in the merged text, then locate which
            # physical line holds it so we can do a line-level replacement.
            new_val_str = format_value(value)
            modified = self._replace_key_in_block(block, key, new_val_str)
            if modified:
                return True

        return False

    def set_pipe_parameter(self, flowpath_label: str, pipe_label: str,
                           key: str, value) -> bool:
        """Find PIPE LABEL=pipe_label inside FLOWPATH LABEL=flowpath_label and set KEY=value."""
        # Locate the target flowpath by scanning NETWORKCOMPONENT blocks
        nc_ranges = self._find_network_component_ranges()

        for nc_range in nc_ranges:
            header_idx = nc_range['header_idx']
            child_ranges = nc_range['children']  # list of (start_idx, end_idx, keyword)
            end_idx = nc_range['end_idx']

            # Check if this NC is the right FLOWPATH
            header_text = self.raw_lines[header_idx].rstrip('\r\n').strip()
            if 'FLOWPATH' not in header_text.upper():
                continue
            header_label = _get_label_from_text(header_text)
            if header_label.lower() != flowpath_label.lower():
                # Also check TAG
                m = re.search(r'TAG\s*=\s*(\S+)', header_text, re.IGNORECASE)
                tag = m.group(1).strip('"\'') if m else ''
                if tag.lower() != flowpath_label.lower():
                    continue

            # Inside this flowpath, find PIPE with the right label
            new_val_str = format_value(value)
            for child in child_ranges:
                if child['keyword'] != 'PIPE':
                    continue
                child_label = _get_label_from_text(child['merged_text'])
                if child_label.lower() != pipe_label.lower():
                    continue
                block = _LogicalBlock('PIPE', child['indices'], child['merged_text'])
                if self._replace_key_in_block(block, key, new_val_str):
                    return True

        return False

    def set_node_parameter(self, node_label: str, key: str, value) -> bool:
        """Find NODE LABEL=node_label and set KEY=value."""
        nc_ranges = self._find_network_component_ranges()
        new_val_str = format_value(value)

        for nc_range in nc_ranges:
            header_idx = nc_range['header_idx']
            header_text = self.raw_lines[header_idx].rstrip('\r\n').strip()
            if 'NODE' not in header_text.upper():
                continue
            header_label = _get_label_from_text(header_text)
            if header_label.lower() != node_label.lower():
                m = re.search(r'TAG\s*=\s*(\S+)', header_text, re.IGNORECASE)
                tag = m.group(1).strip('"\'') if m else ''
                if tag.lower() != node_label.lower():
                    continue

            # Modify parameter on the header line or its continuation
            indices = nc_range['header_indices']
            merged = ''.join(
                self.raw_lines[idx].rstrip('\r\n').rstrip('\\').lstrip() if idx != indices[0]
                else self.raw_lines[idx].rstrip('\r\n').rstrip('\\')
                for idx in indices
            )
            block = _LogicalBlock('NETWORKCOMPONENT', indices, merged)
            if self._replace_key_in_block(block, key, new_val_str):
                return True

            # Also search children
            for child in nc_range['children']:
                block = _LogicalBlock(child['keyword'], child['indices'], child['merged_text'])
                if self._replace_key_in_block(block, key, new_val_str):
                    return True

        return False

    def add_keyword(self, keyword: str, params: dict,
                    after_keyword: str = None) -> bool:
        """Add a new top-level keyword line.

        If after_keyword is given, inserts after the last occurrence of that
        keyword. Otherwise inserts before ENDCASE (or at end of file).

        Returns True always (insertion always succeeds).
        """
        # Build the new line
        parts = [keyword]
        for k, v in params.items():
            parts.append(f"{k}={format_value(v)}")
        new_line = " ".join(parts) + "\n"

        insert_idx = self._find_insert_index(after_keyword)
        self.raw_lines.insert(insert_idx, new_line)
        self._dirty = True
        return True

    def remove_keyword(self, keyword: str, label: str = None) -> bool:
        """Remove a keyword block (and its continuation lines).

        If label is given, removes the specific instance matching LABEL=label.
        Returns True if found and removed, False otherwise.
        """
        keyword_upper = keyword.upper()
        blocks = _build_logical_blocks(self.raw_lines)

        for block in reversed(blocks):  # reverse so indices stay valid during removal
            if block.keyword != keyword_upper:
                continue
            if label is not None:
                block_label = _get_label_from_text(block.merged_text)
                if block_label.lower() != label.lower():
                    continue

            # Remove lines (reverse order to preserve indices)
            for idx in sorted(block.line_indices, reverse=True):
                del self.raw_lines[idx]
            self._dirty = True
            return True

        return False

    def save(self, filepath: str = None) -> str:
        """Write modified lines to file.

        Uses original filepath if none given. Returns the path written to.
        """
        out_path = str(filepath) if filepath else self.filepath
        with open(out_path, 'w', encoding='utf-8') as fh:
            fh.writelines(self.raw_lines)
        return out_path

    @staticmethod
    def format_value(value) -> str:
        """Convert a Python value to .genkey format string."""
        return format_value(value)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _replace_key_in_block(self, block: _LogicalBlock,
                               key: str, new_val_str: str) -> bool:
        """Replace KEY=<old> with KEY=<new_val_str> within a logical block.

        Works by checking each physical line in block.line_indices in order.
        Returns True if the replacement was made.
        """
        pat = _key_pattern(key)

        for idx in block.line_indices:
            raw = self.raw_lines[idx]
            # Strip trailing newline for manipulation; preserve it at the end
            eol = ''
            if raw.endswith('\r\n'):
                eol = '\r\n'
                text = raw[:-2]
            elif raw.endswith('\n'):
                eol = '\n'
                text = raw[:-1]
            else:
                text = raw

            if not pat.search(text):
                continue

            new_text, replaced = _replace_value_in_text(text, key, new_val_str)
            if replaced:
                self.raw_lines[idx] = new_text + eol
                self._dirty = True
                return True

        return False

    def _find_insert_index(self, after_keyword: str = None) -> int:
        """Return the line index at which to insert a new keyword line."""
        n = len(self.raw_lines)

        if after_keyword:
            after_upper = after_keyword.upper()
            last_match = -1
            blocks = _build_logical_blocks(self.raw_lines)
            for block in blocks:
                if block.keyword == after_upper:
                    last_match = block.last_line

            if last_match != -1:
                return last_match + 1

        # Find ENDCASE
        for i, raw in enumerate(self.raw_lines):
            if raw.strip().upper() == 'ENDCASE':
                return i

        return n

    def _find_network_component_ranges(self) -> list:
        """Return list of dicts describing each NETWORKCOMPONENT block.

        Each dict has:
          header_idx        : int   (line index of NETWORKCOMPONENT line)
          header_indices    : list  (all physical lines of the header)
          end_idx           : int   (line index of ENDNETWORKCOMPONENT)
          children          : list  of dicts with keys:
                                keyword, indices, merged_text
        """
        ranges = []
        i = 0
        n = len(self.raw_lines)

        while i < n:
            raw = self.raw_lines[i].rstrip('\r\n').strip()
            if raw.upper().startswith('NETWORKCOMPONENT') and not raw.upper().startswith('ENDNETWORKCOMPONENT'):
                # Collect header (may have continuation lines)
                header_indices = [i]
                merged = self.raw_lines[i].rstrip('\r\n').rstrip('\\')
                j = i
                while self.raw_lines[j].rstrip('\r\n').endswith('\\'):
                    j += 1
                    if j < n:
                        header_indices.append(j)
                        merged += self.raw_lines[j].rstrip('\r\n').lstrip().rstrip('\\')
                    else:
                        break

                nc_info = {
                    'header_idx': i,
                    'header_indices': header_indices,
                    'end_idx': -1,
                    'children': [],
                }

                # Scan children until ENDNETWORKCOMPONENT
                k = header_indices[-1] + 1
                while k < n:
                    child_raw = self.raw_lines[k].rstrip('\r\n')
                    child_stripped = child_raw.strip()

                    if child_stripped.upper() == 'ENDNETWORKCOMPONENT':
                        nc_info['end_idx'] = k
                        k += 1
                        break

                    if child_stripped and not child_stripped.startswith('!'):
                        # Collect child (with continuation)
                        child_indices = [k]
                        child_merged = child_raw.rstrip('\\').lstrip()
                        while self.raw_lines[k].rstrip('\r\n').endswith('\\'):
                            k += 1
                            if k < n:
                                child_indices.append(k)
                                child_merged += self.raw_lines[k].rstrip('\r\n').lstrip().rstrip('\\')
                            else:
                                break
                        child_kw_m = re.match(r'\s*([A-Za-z_][A-Za-z0-9_]*)', child_raw)
                        child_kw = child_kw_m.group(1).upper() if child_kw_m else ''
                        nc_info['children'].append({
                            'keyword': child_kw,
                            'indices': child_indices,
                            'merged_text': child_merged.strip(),
                        })

                    k += 1

                ranges.append(nc_info)
                i = k
            else:
                i += 1

        return ranges


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Modify KEY=VALUE pairs in an OLGA .genkey file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python genkey_writer.py case.genkey INTEGRATION ENDTIME "96 h"
  python genkey_writer.py case.genkey OPTIONS COMPOSITIONAL ON
  python genkey_writer.py case.genkey PIPE DIAMETER "0.6 ft" --label Pipe_1
  python genkey_writer.py case.genkey MATERIAL CONDUCT "45 W/m-C" --label Steel
        """,
    )
    parser.add_argument("filepath", help="Path to the .genkey file")
    parser.add_argument("keyword", help="Keyword to find (e.g. INTEGRATION, PIPE)")
    parser.add_argument("key", help="Parameter key to modify (e.g. ENDTIME, DIAMETER)")
    parser.add_argument("value", help="New value (e.g. '96 h', ON, 0.5)")
    parser.add_argument("--label", default=None,
                        help="LABEL of the specific keyword instance to modify")
    parser.add_argument("--output", default=None,
                        help="Output filepath (default: overwrite input)")

    args = parser.parse_args()

    path = Path(args.filepath)
    if not path.exists():
        print(f"Error: file not found: {args.filepath}", file=sys.stderr)
        sys.exit(1)

    # Parse value: try to interpret as Python literal for common types
    raw_val = args.value
    value = _parse_cli_value(raw_val)

    writer = GenkeyWriter(str(path))
    success = writer.set_parameter(
        keyword=args.keyword,
        key=args.key,
        value=value,
        label=args.label,
    )

    if not success:
        label_hint = f" (LABEL={args.label})" if args.label else ""
        print(
            f"Warning: {args.keyword}{label_hint} KEY={args.key} not found.",
            file=sys.stderr,
        )
        sys.exit(2)

    out = writer.save(args.output)
    print(f"Written: {out}")


def _parse_cli_value(raw: str):
    """Attempt to interpret a CLI value string into a Python type.

    Tries in order: bool keywords, int, float, then keeps as str.
    This preserves strings like "96 h" (number+unit) as-is so that
    format_value() will emit them correctly.
    """
    upper = raw.upper()
    if upper in ("ON", "YES", "TRUE"):
        return True
    if upper in ("OFF", "NO", "FALSE"):
        return False
    try:
        iv = int(raw)
        if str(iv) == raw:
            return iv
        return float(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


if __name__ == "__main__":
    main()
