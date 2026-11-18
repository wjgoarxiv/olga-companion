# Code review findings (xhigh, 2026-11-18)

Whole-repo review of `src/olga_companion` and `frontend/src`. No code changed. Six findings were reproduced by running code; no OLGA or Multiflash run. Not reviewed in depth: `windows_broker*`, the Tauri shell, most `llm/*` auth flows.

| # | Severity | Type | File:line | Summary | Repro |
|---|---|---|---|---|---|
| R1 | High | bug | `src/olga_companion/case_spec_validation.py:145` | `"equipment": []` is rejected as unsupported equipment | validate_case_spec with the empty key → valid=False; key removed → valid=True (reproduced) |
| R2 | High | bug | `src/olga_companion/patrol_sanitization.py:13` | `_PRIVATE_PATH` eats units: `kg/s` → `kg[private-path]` | "CFL 5 m/s", "GOR 100 Sm3/Sm3" corrupted in findings and stop reasons (reproduced) |
| R3 | High | bug | `src/olga_companion/units.py:130` | One NaN in a series fails the whole trend/CSV/PDF; `°C`→`C` does an offset round trip | [1, nan, 3] raises; 15.1 → 15.100000000000023 (reproduced) |
| R4 | High | bug | `src/olga_companion/multiflash_direct.py:233` | `make_tab` ignores MFIN_MF `load_errors`; `pickup_tab` uses `assert` (500, vanishes under -O) | an .mfl with load error codes can still yield a wrong but valid-looking .tab |
| R5 | High | bug | `src/olga_companion/run_companions.py:34` | PVTFILE pattern reads `!` comment lines and swallows trailing commas | `! FILES PVTFILE="old.tab"` → preflight refuses "table not next to it"; `fluid.tab,` reported missing (reproduced) |
| R6 | Medium | perf | `src/olga_companion/olga_runtime_detection.py:16` | `/health` every 20 s SHA-256s every OLGA exe and spawns two Python probes | constant disk/CPU churn while the app is open |
| R7 | Medium | bug | `src/olga_companion/case_compiler.py:505` | centerline/diameter compared as raw floats vs 15-digit round trip | XEND 30.480000000000004 → CaseCompileError (reproduced) |
| R8 | Medium | bug | `src/olga_companion/run_companions.py:183` | `stage_companions` uses locale encoding and global `str.replace` | cp949 + Korean comments → UnicodeEncodeError 500 or hash mismatch; `a.tab` inside `data_a.tab` rewritten |
| R9 | Medium | bug | `frontend/src/resultApi.ts:198` | profile figure export drops the selected timestep; backend renders all timesteps | exported figure ≠ screen; 120 s timeout on long runs |
| R10 | Medium | bug | `src/olga_companion/fluid_table.py:329` | duplicate components (methane/C1) and unsorted or duplicate grids accepted for Multiflash | engine error or wrong table only after launch |
| R11 | Medium | bug | `src/olga_companion/case_transactions.py:262` | ENDTIME rewrite rounds (7200.25→7200.2) or fails as "target does not exist"; card shows typed value | integer or exponent ENDTIME tokens cannot be edited |
| R12 | Medium | bug | `src/olga_companion/llm/api_key_connections.py:79` | `WinDLL('advapi32')` without `use_last_error` → errors read as 0 | failed CredDeleteW reported as "key removed" while the secret stays |
| R13 | Gap | feature gap | `src/olga_companion/case_edit_table.py:29` | edit table covers end time, boundary P/T, source flow, valve opening, roughness only | no controller/PID, heat transfer, wall, diameter, MAXDT/MINDT, output interval; keyword edits stay in sandbox; ramps flattened; valve schedule deleted; sweep skips repeated keywords |
| R14 | Gap | stale status | `src/olga_companion/fluids.py:169` | Multiflash shown as "Gated" though Make .tab works | System status drawer misleads users and QA |
| R15 | UX | i18n | `src/olga_companion/run_solver_findings.py:76` | backend messages mixed: findings Korean-only, failure titles English-only, PVT range both in one string | English UI shows Korean text and vice versa |
