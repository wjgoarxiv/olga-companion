"""Third-party modules the bundled toolkit scripts import, named for PyInstaller only.

The frozen sidecar runs toolkit scripts in its own interpreter (``--tool-script``), and
PyInstaller bundles only modules it can reach from ``olga_companion``
(``--collect-submodules``). Listing them here puts them in the bundle. Nothing imports this
module at runtime; tests/test_toolkit_frozen_imports.py keeps the list complete.
"""
# ruff: noqa: F401

try:
    import matplotlib
    import matplotlib.animation
    # savefig loads the writer for each file format at call time, out of PyInstaller's
    # sight; the app and the toolkit write .png and .pdf.
    import matplotlib.backends.backend_agg
    import matplotlib.backends.backend_pdf
    import matplotlib.colors
    import matplotlib.font_manager
    import matplotlib.pyplot
    import numpy
    import pandas
    import pyfas
    import pyfas.Ppl
    import pyfas.Tpl
except ImportError:  # the results extra is optional in a source checkout
    pass
