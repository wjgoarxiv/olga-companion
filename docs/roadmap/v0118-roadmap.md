# Plan: OLGA Companion roadmap 0.1.18 → 0.1.19 → 0.2.0

Status: APPROVED by the owner 2026-11-18 ("이대로 승인"). Sources: `.litclaude/evidence/next-review/FINDINGS.md` (R1–R15), `.litclaude/brainstorm/next-ideas.md` (471 ideas → 37 clusters → top 10, critic pass).

## PIN
- Objective: ship the review fixes first (0.1.18), then the top ideas (0.1.19), then wider edit coverage (0.2.0).
- Non-goals: no new runtime deps without a yes; no loosening of approval cards; no review of the Tauri shell or broker in these milestones except where named.
- Boundaries: commit/push to private master allowed; public repush, release, Pages need the owner's yes at that moment. Release notes of 0.1.18 include 17403a2, 60dc180, c69e0ac, 7cff3cd.
- Loop per item: PIN → RED → GREEN → VERIFY → SURFACE (PVT Verify, CDP 9223) → REVIEW → CLEAN → RECORD.

## Milestone 0.1.18 — fixes first

- [ ] **M1 R12 credential errors.** Action: `WinDLL('advapi32', use_last_error=True)` in `src/olga_companion/llm/api_key_connections.py`; a failed delete is reported. Output: fix + test. Verification: test with a mocked failing CredDeleteW fails before, passes after.
- [ ] **M2 Golden regression set (idea 2).** Action: one failing repro test each for R1, R2 (plus inverse test: real `C:\` and `/home` paths still redacted), R3, R5, R7, R11 under `tests/`. Output: 7+ tests, all RED on HEAD. Verification: `uv run pytest -q -k golden` shows them failing before M3.
- [ ] **M3 Fix R1 R2 R3 R5 R7 R11.** Files: `case_spec_validation.py`, `patrol_sanitization.py`, `units.py`, `run_companions.py`, `case_compiler.py`, `case_transactions.py` (+ card shows the saved ENDTIME). Verification: M2 tests GREEN; full suite green; safety ≥ 900.
- [ ] **M4 R4 + R10 Multiflash table inputs.** Action: `make_tab` refuses on `load_errors`; `pickup_tab` assert → 4xx "not ready"; duplicate components and unsorted/duplicate grids refused before launch. Verification: unit tests with a canned child outcome; PVT: bad .mfl shows the load error.
- [ ] **M5 R8 encoding.** Action: UTF-8 read/write in `stage_companions`, token-exact reference rewrite. Verification: test with Korean comments under a cp949 locale simulation; `data_a.tab` untouched.
- [ ] **M6 R9 profile export.** Action: pass timestep from `frontend/src/resultApi.ts`; backend renders only that step. Verification: frontend test asserts the timestep in the request; backend test renders one PNG.
- [ ] **M7 R13a silent data loss.** Action: ramped source edit and valve schedule edit either keep the schedule or refuse with a clear message; sweep handles or refuses repeated keywords explicitly. Verification: tests per case; no silent flattening.
- [ ] **M8 R15 three sites + R14 label + R6 cache.** Action: locale for solver findings, failure titles, PVT range text; Multiflash status reflects the real Make .tab state; cache `detect_olga` by (path, size, mtime). Verification: en/ko tests; status test; health call does not re-hash unchanged exes.
- [ ] **M9 Ride-alongs.** CSV NaN-safe with BOM option (idea 1); stop-reason wording en/ko (idea 5 part 1); audit tests: approved-hash run gate, write-scope refusal. Verification: tests; PVT screenshot of a failure panel in en and ko.
- [ ] **M10 Release 0.1.18.** Standard chain (bump 7 files, full gates, run-release, check-release, verify-sig, export + scan 0 hits). Public steps only after the owner's yes.

## Milestone 0.1.19 — top ideas
- [ ] **N1 Fluid provenance and staleness (idea 3).** Sidecar with .mfl hash and grid at make_tab, listed on the approval card; preflight says fresh / stale / unknown. Verification: edit .mfl → stale; no sidecar → unknown.
- [ ] **N2 Warn-only lint + keyword coverage map (ideas 4, 6).** Read-only rules over the exact .genkey; map of editable vs refused keywords. Verification: zero warnings on good fixtures; each rule has a positive fixture.
- [ ] **N3 Stop-reason keyword pointer (idea 5 part 2).** Evidence line through safe_diagnostic_text. Verification: fixtures for 5 stop types.
- [ ] **N4 Remaining number-parse sites (idea 7).** One strict parser; ambiguous text refused. Verification: property tests.
- [ ] **N5 Two-case diff (idea 8)** via the case registry, and **N6 cross-run overlay (idea 9)** refusing unit or time-base mismatch. Verification: fixture diffs and overlays.
- [ ] **N7 String catalogue and glossary (idea 10)**; version matrix and support bundle; stretch: grounded-numbers check, run-log health panel.
- [ ] **N8 Release 0.1.19** (same chain and gates).

## Milestone 0.2.0 — wider OLGA coverage
- [ ] **P1 R13b new edit keys:** controller/PID, heat transfer, wall, diameter, MAXDT/MINDT, output interval; all through plan → validate → diff → approve → new copy.
- [ ] **P2 Remedy loop:** stop reason → proposed edit on an approval card (needs N3).
- [ ] **P3 Sweep analysis and early warning; accessibility pass; beginner lessons.**
- [ ] **P4 Install/update channels** only after a review of the Tauri shell and broker.
- [ ] **P5 Release 0.2.0.**

## Stop rules
Stop on a red safety test, a scan hit, a change that would let an action skip an approval card, an unapproved public step, or the same failure twice.

## DoneClaim (per milestone)
All items ticked; RED-then-GREEN tests recorded; full backend + frontend + typecheck green; safety ≥ 900; PVT screenshots for each UI change in en/ko and light/dark; release receipts (check-release, verify-sig, verify-hosted 7/7) after the owner's yes.
