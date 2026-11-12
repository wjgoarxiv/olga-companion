# Tutorial demo case

Synthetic air–water horizontal pipe for the 7-step guided tutorial. Every
value here is invented for teaching; nothing comes from customer data.

- `demo_case.json` — CaseSpec v2, single 500 m horizontal pipe (`PIPE_1`,
  0.2 m diameter), inlet 8 bar / 40 °C, outlet 2 bar / 30 °C. Passes
  `case_spec.validate_case_spec`; see `tests/test_tutorial_case.py`.
- Fluid table — not bundled here. The tutorial asks the agent to stage the
  app's bundled generic air–water table (`fluids_starter_tab`, label
  `AIR_WATER`, 0–80 °C, 0.5–20 bar) as `air_water.tab` first, because the
  demo pressures and temperatures stay inside that range. Approval-gated,
  like every tutorial file write.
