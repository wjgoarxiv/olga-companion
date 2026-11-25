"""Child process that runs the installed Multiflash engine once to write an OLGA .tab.

It runs alone so an engine crash cannot stop the app. Standard library only: the packaged
sidecar runs it with ``--multiflash-table <request.json>``, and a development checkout can run
this file with any Windows Python.

The calls follow the engine's own exports in Multiflash 7.3 (MFBJ01.dll, Intel Fortran with
the CVF interface, so each string is followed by its length):
``MFIN_MF(text, len, nerr, mxerr, ierr)`` runs the .mfl commands, then
``MFOLGA(ist, moles, tab, len, hyd, len, wax, len, np, p_pa, nt, t_k, title, len, nerr, mxerr, ier)``
writes the table over the pressure (Pa) and temperature (K) grid.
``MF_PVT_TABLE_ENABLE_HA_WATERPHASE(flag)`` sets the high-accuracy water model first.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from typing import Any

_MAX_ERRORS = 50


def run(request: dict[str, Any]) -> dict[str, Any]:
    engine_dir = str(request["engine_dir"])
    os.add_dll_directory(engine_dir)
    # The .mfl names its databanks relative to the engine folder ("puredata INFODATA").
    os.chdir(engine_dir)
    dll = ctypes.CDLL(os.path.join(engine_dir, "MFBJ01.dll"))

    text = str(request["mfl_text"]).encode("utf-8", errors="replace")
    nerr = ctypes.c_int(0)
    mxerr = ctypes.c_int(_MAX_ERRORS)
    ierr = (ctypes.c_int * _MAX_ERRORS)()
    dll.MFIN_MF(ctypes.c_char_p(text), ctypes.c_size_t(len(text)), ctypes.byref(nerr), ctypes.byref(mxerr), ierr)
    load_errors = [int(code) for code in ierr[: min(nerr.value, _MAX_ERRORS)]]

    # On only when the .mfl table command says HAWATER.
    dll.MF_PVT_TABLE_ENABLE_HA_WATERPHASE(ctypes.byref(ctypes.c_int(1 if request.get("ha_water", False) else 0)))

    moles = [float(value) for value in request["moles"]]
    pressures = [float(value) for value in request["pressures_pa"]]
    temperatures = [float(value) for value in request["temperatures_k"]]
    tab = str(request["tab_path"]).encode("utf-8")
    title = str(request["title"]).encode("utf-8")
    blank = b" "
    ist = ctypes.c_int(0)
    n_p = ctypes.c_int(len(pressures))
    n_t = ctypes.c_int(len(temperatures))
    nerr2 = ctypes.c_int(0)
    mxerr2 = ctypes.c_int(_MAX_ERRORS)
    ier = (ctypes.c_int * _MAX_ERRORS)()
    dll.MFOLGA(
        ctypes.byref(ist), (ctypes.c_double * len(moles))(*moles),
        ctypes.c_char_p(tab), ctypes.c_size_t(len(tab)),
        ctypes.c_char_p(blank), ctypes.c_size_t(0),
        ctypes.c_char_p(blank), ctypes.c_size_t(0),
        ctypes.byref(n_p), (ctypes.c_double * len(pressures))(*pressures),
        ctypes.byref(n_t), (ctypes.c_double * len(temperatures))(*temperatures),
        ctypes.c_char_p(title), ctypes.c_size_t(len(title)),
        ctypes.byref(nerr2), ctypes.byref(mxerr2), ier,
    )
    table_errors = [int(code) for code in ier[: min(nerr2.value, _MAX_ERRORS)]]
    return {"ok": not table_errors, "errors": table_errors, "load_errors": load_errors}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: multiflash_child.py <request.json>", file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as handle:
        request = json.load(handle)
    result = run(request)
    with open(str(request["result_path"]), "w", encoding="utf-8") as handle:
        json.dump(result, handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
