"""Recognise network paths before anything touches them.

On Windows, resolving or stat-ing ``\\\\host\\share\\file`` opens an SMB
connection and sends the user's NTLM challenge response to that host, so a
path taken from a case file or a tool argument is checked as text first.
"""

from __future__ import annotations

import re

# ``\\?\C:\...`` is the local extended-length form Windows gives installed apps for their own folders.
_LOCAL_EXTENDED = re.compile(r"\\\\\?\\[A-Za-z]:(\\|\Z)")


def is_network_path(value: object) -> bool:
    """True for UNC and device forms: ``\\\\host``, ``//host``, ``\\\\?\\UNC``, ``\\\\.\\``.

    ``\\\\?\\C:\\`` (a local drive in extended-length form) is not a network path.
    """
    text = str(value or "").strip().strip("\"'").strip().replace("/", "\\")
    return text.startswith("\\\\") and not _LOCAL_EXTENDED.match(text)
