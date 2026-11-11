# OlgaCopilot Architecture (v2)

## Boundaries

- **Project root:** `06_APP-making`. Git history is append-only; baseline preserved at tag `v0.1-workbench`.
- **Frontend port:** `5273`. **Sidecar port:** `8865`. Localhost only.
- **Forbidden mutation targets:** HYSYS Companion repo (read-only architecture reference) and any external app repository.
- **Sandbox root:** `var/` (sandbox runs, exports, chats) — git-ignored.
- **Secrets:** OAuth tokens live under `~/.olga_copilot/` (0600), never in the repo, logs, or frontend.

## Runtime components (v2 target — built across T1–T4)

```
frontend (React/Vite :5273)                     sidecar (FastAPI :8865, src/olga_companion)
  ChatView ────────── SSE ─────────────────────▶ /api/chat + /api/chat/stream
  ApprovalCard ─────── POST ───────────────────▶ /api/approvals/execute    (one-shot pending action)
  ProviderPanel ────── GET/POST ────────────────▶ /api/providers/*          (catalog, status, OAuth flows)
  EnvDrawer ────────── GET ─────────────────────▶ /health                   (quiet capability state)
                                                     │
                                                     ▼
                                        agent/runtime.py — provider-agnostic loop
                                        (async AgentEvent generator: text_delta, thinking,
                                         tool_call, tool_result, approval_required, done, error)
                                                     │ uses
                        ┌────────────────────────────┼─────────────────────────────┐
                        ▼                            ▼                             ▼
                llm/ (ported layer)          agent/tools.py                agent/approvals.py
                protocol.py: ToolCall,       allowlisted belt over the     single-use, TTL, digest-
                StreamResult,                v0.1 adapters; byte-capped    bound tokens; minted only
                ConversationBuilder          results (16 KB + artifact     by a human click on the
                adapters/: openai_chat,      path); no shell, no free      server-rendered command
                openai_responses,            file write
                antigravity, copilot                 │
                codex_oauth · copilot_auth           ▼
                catalog.py · factory.py      v0.1 adapter modules (UNCHANGED API + 71 tests):
                (headers→settings→default)   genkey_static · fluids · runner · results ·
                                             evaluation · reports · opc  (+ diagnostics.py NEW:
                                             solver_diagnostics / run_monitor wrappers)
                                                     │
                                                     ▼
                                             OLGA toolkit scripts (058_olga-copilot, allowlisted)
                                             and opi.exe (WSL interop dev / native Windows packaged)
```

## Provider layer (ported HysysCompanion pattern)

- One agent loop speaks three API dialects through `ApiClient`/`ConversationBuilder` implementations: OpenAI Chat Completions, OpenAI Responses, Antigravity (Gemini); Copilot rides its dedicated client.
- Auth is subscription OAuth: Codex tokens are imported from `$CODEX_HOME/auth.json` when present (app-owned refresh copy in `~/.olga_copilot/codex_tokens.json`); Copilot uses the device flow.
- Selection resolver: per-request headers (`x-llm-provider/-model/-variant`) → saved settings → default `("openai", DEFAULT_MODEL, "medium")`.
- Model catalog is honest and static per provider; providers without a wired backend (anthropic, openrouter) report empty lists.

## Safety contract (load-bearing)

1. **Out-of-band approval.** When the model requests a side-effectful tool, the runtime stops and stores the exact normalized call as an opaque, context-bound pending action. A human click calls authenticated `POST /api/approvals/execute`; the server claims that pending action once, mints and consumes the digest-bound capability internally, and dispatches only the stored payload. Capability material never enters UI text, SSE, chat history, or a provider request. Agent tool schemas contain no `approved`/`override` field.
   Only dispatch errors proven to occur before handler entry release the claim for retry. An unconfirmed dispatch failure after entry, including result validation or bounding failure, seals the action as `uncertain` and returns HTTP 409 without the raw error. Repeated requests and journal recovery preserve that state instead of dispatching again.
   A continuation after an approved action goes only to the provider and model recorded on that approval. A missing, malformed or unknown identity seals the continuation without contacting any provider; a disconnected original provider stays retryable and never falls back to another one. The approved action itself is never re-dispatched by a continuation.
   A model turn is bound to the workspace generation and active case it started in: if the user switches either during the model wait, its tool request is discarded instead of running against the new case.
   **Bounded action plan (2026-10-31).** One approval may be an `action_plan`: an ordered list of at most six steps. The allowed kinds are `fluids_draft_mfl`, `case_publish` and `run_execute`, plus `fluids_generate_tab` only when the sidecar starts with `OLGA_COMPANION_NATIVE_TAB=1`. `run_cancel`, `sweep_cancel`, `sweep_execute`, `genkey_save` and `multiflash_open` each stay on their own card. A digest over the ordered steps, the session, the workspace generation and the plan call binds the list, so a later turn cannot add, reorder or append a step. At each step's turn the server re-validates that step, mints a fresh single-use token, and stops at the first failure; later steps are answered not run. A plan holds at most one run. A run bound to an earlier publish names no case of its own: at its turn the server checks that the published file still matches the publish receipt's bytes, previews that case again, and refuses the run unless the check is clean. **Failed** means the outcome is known and the step did not complete (a refusal before dispatch, a refused run, or bytes that no longer match). **Uncertain** means the handler had been entered and the outcome could not be confirmed: finished steps stay finished, that step is not retried, and it is not reported as a definite failure.
2. **Allowlisted tools only.** The agent has no shell and no free file write; every tool maps to a v0.1 adapter or the two new diagnostics wrappers. File reads are byte-capped.
3. **Untrusted content stays data.** Text from genkey/tab/out files never elevates permissions — enforced by design and proven by the injection-corpus test suite.
4. **Evidence over narration.** Every engineering claim in chat traces to a tool result; the system prompt encodes the NORTHSTAR clause.
5. **Fail-closed gates.** v0.1 capability gating is unchanged in the backend; the UI presents it as a quiet environment drawer.
6. **Local API protection.** The sidecar binds only to loopback. Every `/api/*` request except the no-store token bootstrap requires the per-boot session token; loopback `Host` and the effective frontend/sidecar `Origin` ports (plus `tauri://localhost`) are validated before dispatch.
7. **File trust boundaries.** Case/PVT inputs resolve only inside the active workspace or app sandbox, with canonical and symlink-safe checks. Result/report inputs resolve only inside app-owned run/export roots. Save As accepts only contained exports and publishes with no-clobber or recoverable atomic replacement semantics.
8. **Bounded process ownership.** Run and sweep timeouts are strict integers in `1..604800` (seven days, the Explorer broker ceiling). Direct POSIX test/dev runtimes run in their own process group; native OLGA engines run under the Windows broker Job Object, so cancel and timeout terminate the owned process tree.
9. **No invented physics.** CaseSpec v2 has no default for fluid label, source/sink temperature, pipe roughness or the adiabatic-versus-ambient heat-exchange choice (ambient needs its coefficient, ambient temperature and wall). The toolkit validator rules that require a PVT label (X010) and a heat-transfer model (X011) are unchanged (X011 has always exempted an explicit `OPTIONS TEMPERATURE=ADIABATIC`; CaseSpec uses that only when the user chose it); the compiler satisfies them from the stated values and the round trip compares each one. A v1 compiler artifact is classified as legacy and is never silently migrated.
10. **Receipt-verified results.** A result is receipt-backed only if the run receipt lists it and its current bytes still match the recorded digest; otherwise it is shown as changed or as having no receipt.
11. **Updates never end work silently.** Installing an update stops the sidecar and the runs it supervises, so the native `stop_sidecar` command first asks the backend (`POST /api/update/prepare`) and refuses unless it answers `safe` and `confirmed` with nothing starting. Every non-terminal or unreadable run receipt counts as unknown and blocks; a "safe" answer closes the shared launch gate (`run_update_gate`, also taken by `execute_run` and the whole of `launch_sweep`) so no run can start between the check and the stop. The gate is never reopened by time; only the same attempt (`X-Update-Prepare-Id`) reopens it via `POST /api/update/release`, which the native side sends when it gives up or the stop does not take. Another attempt's prepare or release is refused while that latch is held; it is never taken over. The command is `async` so a stalled backend cannot freeze the window.
12. **Tools stay in the context they were checked in.** A read/long tool runs without the workspace lock, so each path it resolves re-checks the turn's workspace generation (`workspace.bound_to`), and it cannot record a case as active after the user chose another (`set_active_path` refuses). Approved side effects still run under `expected_context`.
13. **PVT presence is not validation.** Simulation setup requires every referenced PVT companion to have a positive validation result; `missing=0` alone cannot make it ready. A failed or timed-out validator, an incomplete JSON report, or an absent/failed companion check refuses readiness. This guard does not itself establish support for additional PVT formats; verify the format before interpreting rejection as a physical-input defect.

### Static PVT format support

- The bundled reader supports legacy PH property arrays and the observed `MESHTYPE=STANDARD` column/`PVTTABLE POINT` profile for keyword `PHASE=TWO` and `PHASE=THREE`. STANDARD support requires explicit pressure in Pa, temperature in C, and one unitless `TOTWATERFRACTION` in `[0, 1]`. Other phases, units and composition grids are not qualified and are rejected for column/POINT input.
- STANDARD preserves declared column order and names, including `ROHL` and `ROWT`; it never synthesizes `ROL`. Full validation requires `PT`, `TM`, the three density columns, finite row values, unique increasing axes, and exactly one row per pressure-temperature coordinate. This is a structural minimum, not thermodynamic or solver qualification.
- Header-only inspection exposes declared columns and temperature-grid metadata, with `point_data_loaded=false` and no validated row count. Only full parsing checks POINT contents and completeness. Legacy header inspection now retains metadata after `NOENTHALPY`, before property arrays.
- Temperature coverage and the text `Temperature` field use the explicit grid, never bubble temperatures. Existing `bubble_temperature` JSON metadata remains separate; the text calls it `Bubble T`. Without an explicit temperature grid, no temperature-coverage conclusion is made. STANDARD cross-checks normalize absolute Pa/kPa/MPa/bar/bara and C/K boundary values; missing, unknown or gauge units fail with `V010` instead of a guessed conversion.
- Passing these checks does not resolve native OLGA property-value exceptions. Owner GENKEY/TAB files remain unchanged. Existing installers must be rebuilt before they can supply this source-level support.

### Local table tools (2026-10-31)

- `fluids_compare_tab` is read-only. It compares two `.tab` files by column, node and region and returns the report. It writes nothing and does not ask for approval.
- `fluids_generate_tab` is local-only. The tool, its prompt text and its plan step exist only when the sidecar starts with `OLGA_COMPANION_NATIVE_TAB=1`. After one approval it writes a new OLGA keyword table and validates it. The table is an independent table, not Multiflash-identical. A release build excludes the engine and never sets the flag.

## Storage

| Data | Location | Notes |
|---|---|---|
| Chat sessions | `var/chats/<session>.jsonl` | no token material; user case data — local only |
| Sandbox runs | `var/sandbox/runs/<id>/` | case copy + PVT companions + run.log + outputs |
| Exports | `var/exports/` | plots, CSV, reports (containment-checked) |
| Save As safety retention | hidden same-filesystem directories adjacent to selected folders + private registry under `~/.olga_copilot/save-as-retention/` | verified POSIX modes or protected Windows DACLs; two captured safety copies per existing-file publication; app-global cross-process 512 MiB / 128-file / 64-directory hard cap; cleanup only while every sidecar is stopped |
| Save As recovery records | `~/.olga_copilot/save-as-recovery/` | opaque-ID mappings for retained backups; root, temporary, and final records require verified POSIX modes or protected Windows DACLs |
| OAuth tokens | `~/.olga_copilot/` | 0600; outside the repo |
| Evidence ledger | `.litopencode/litgoal/lit-loop/` | append-only, authoritative for what was verified |

## Dev vs packaged drift

- Dev: WSL sidecar; OLGA via `/mnt/c/...` globs and WSL interop (`opi.exe` exit-0 verified).
- Packaged: native Windows sidecar (PyInstaller); detection must also use `C:\Program Files\...` glob forms. The LLM layer is pure pip Python — no extra runtime to bundle.
- **Local table engine (2026-10-31).** A release still bundles no extra runtime. The table engine is pure Python on the sidecar's own interpreter, under 100 KB of source, and the release sidecar excludes it. A local PVT Verify build may include it, with `OLGA_COMPANION_NATIVE_TAB` set by that build's runtime hook. See `docs/PACKAGING.md`.

## Pipe-table import (2026-11-01)

A network can be built from a pipe table instead of a model-written CaseSpec. `pipe_table.py` reads CSV or xlsx with the standard library only. `pipe_table_import.py` turns the rows into a CaseSpec v3: flowpaths, junctions, boundaries and scheduled valves, with labels generated in table order. `segmentation.py` grades the sections of every flowpath. The spec is kept in `case_draft_store.py`, which is private, expiring and revision-checked; the model refers to it by id and sees only summaries, because a large network does not fit in one model reply or tool result. Saving goes through the usual `case_edit_plan` and `case_publish` approval and writes a new file. CaseSpec v3 adds length/elevation pipes, graded sections, valve schedules, larger caps and pass-through junctions; v2 specs keep their grammar and bytes. Format: `docs/PIPE_TABLE.md`.
