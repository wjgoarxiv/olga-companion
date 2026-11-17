# Tutorial demo case

Synthetic air–water horizontal pipe for the 7-step guided tutorial. Every
value here is invented for teaching; nothing comes from customer data.

- `demo_case.json` — CaseSpec v2, single 500 m horizontal pipe (`PIPE_1`,
  0.2 m diameter), inlet 8 bar / 40 °C, outlet 2 bar / 30 °C. Passes
  `case_spec.validate_case_spec`; see `tests/test_tutorial_case.py`.
- Fluid table — not stored in this folder. Installing the example copies the
  bundled generic air–water table (`AIR_WATER`, 0–80 °C, 0.5–20 bar) into
  the workspace under a free name and points the case at that copy. The
  tutorial button calls that install. It does not ask the chat to read this
  folder, which sits outside the user's workspace.
