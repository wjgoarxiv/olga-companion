# Make a .tab from values you already have

The app can write an OLGA PVT table (`.tab`) from property values the user already has: a HYSYS or
PVTsim export, a laboratory table, any spreadsheet. The values are **written as given. Nothing is
calculated, interpolated, filled or corrected**, and the in-house PVT engine is not involved (that
engine stays unreleased, see `docs/PACKAGING.md`). Only the two axes change unit, to Pa and degC.

## The file the user brings

A long-form `.csv` or `.xlsx` in the workspace, one row per pressure and temperature point.

| Column | Header | Notes |
| --- | --- | --- |
| Pressure | `P (bar)`, `Pressure [kPa]`, `P_MPa`, `psia`, `Pa` | Unit in the header, never guessed. Pa, kPa, MPa, bar, bara, barg, psi, psia, psig, atm. Gauge units (barg, psig) add one standard atmosphere. |
| Temperature | `T (C)`, `Temperature (K)`, `degF`, `T_K` | Unit in the header, never guessed. C, degC, K, F, degF, R, degR. |
| Properties | the OLGA keyword: `ROG`, `ROHL`, `VISG`, `VISHL`, `RS`, `CPG`, `CPHL`, `HG`, `HHL`, `TCG`, `TCHL`, `SIGGHL`, ... | Values are taken to be in the OLGA unit of that keyword (below). A header that states another unit is refused, not rescaled. |

OLGA units (from the toolkit validator's keyword table): densities `ROG ROHL ROWT` kg/m3, `DROGDP`
`DROHLDP` `DROWTDP` s2/m2, `DROGDT` `DROHLDT` `DROWTDT` kg/m3/C, `RS` `RSW` kg/kg, viscosities `VISG`
`VISHL` `VISWT` Ns/m2, heat capacities `CPG` `CPHL` `CPWT` J/kg/C, enthalpies `HG` `HHL` `HWT` J/kg,
conductivities `TCG` `TCHL` `TCWT` W/m/C, surface tensions `SIGGHL` `SIGGWT` `SIGHLWT` N/m, entropies
`SEG` `SEHL` `SEWT` J/kg/C. Columns that are not an OLGA keyword are listed and left out.

## Rules

- A complete rectangular grid: every pressure/temperature pair exactly once, no duplicates.
- Pressures and temperatures each strictly increasing in the order they appear (sort the rows first).
  At least two of each; absolute pressure above 0 Pa.
- Every number finite; no empty cells.
- `ROG` and `ROHL` are required. A water-phase column (`ROWT`, `VISWT`, ...) makes the table
  `PHASE = THREE` and needs the total water fraction the user states (`TOTWATERFRACTION`); otherwise
  the table is `PHASE = TWO`.
- `COMPONENTS` and `MOLES` are written only when the user gives them (they must sum to 1). Otherwise
  the header carries the placeholder `COMPONENTS = ( "NOT_STATED" ), MOLES = ( 1 )`, which the OLGA
  validator needs, and says nothing about the fluid.
- No `BUBBLEPRESSURES` or `DEWPRESSURES` are written: they would have to be calculated.

## Two separate steps

1. **Preview (read only).** `POST /api/fluids/tab-import/preview` (`path`, `fluid_label`, optional
   `total_water_fraction`, `sheet`, `components`, `moles`) returns the grid size, the columns, the
   issues, the first lines of the file and the SHA-256 of the exact text. It writes nothing. The
   panel is in the fluid-table flow ("Make a .tab from values you already have"); it only places a
   request in the chat composer.
2. **Write (approval-gated).** The agent tool `fluids_import_tab` (`source_rel`, `tab_rel`,
   `fluid_label`, optional `sheet`, `components`, `moles`, `total_water_fraction`) follows the same
   approval path as `fluids_starter_tab`: no card is offered for a table that would not import; the
   approval is bound to the SHA-256 of the exact text, so a source file that changes after the card
   was shown is refused; the destination is workspace-contained, must end in `.tab`, must not exist
   and is never overwritten; the tool never joins an `action_plan`.

Before anything is offered, the produced text is parsed back with the toolkit `TabParser` (grid,
columns and every value compared) and checked with the toolkit validator. The same validator runs on
the file after it is written.

Code: `src/olga_companion/tab_import.py`; tests: `tests/test_tab_import.py`,
`frontend/tests/tab-import-panel.test.mjs`.
