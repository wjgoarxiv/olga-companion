"""PyInstaller runtime hook for the local PVT Verify sidecar only.

It turns on the in-app table generator before any app module loads. The release recipe in
docs/PACKAGING.md never passes this file, so a release sidecar keeps the generator off.
"""

import os

os.environ["OLGA_COMPANION_NATIVE_TAB"] = "1"
