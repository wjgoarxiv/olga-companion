# OlgaCopilot Roadmap

## Foundation (v0.1, complete — tag `v0.1-workbench`)

M0–M8 built and verified the safety substrate that v2 keeps as its tool belt: allowlisted toolkit adapters for GENKEY create/review/modify-copy, Fluid/PVT inspection and consistency, the sandboxed run orchestrator (detect → validate → approve → execute → cancel/timeout), result parsing/plots/CSV, citation-complete engineering evaluation, report/figure/compare studio with failure-marker honesty, the OPC 5-condition gate, Tauri packaging config, and 71 backend tests. The v0.1 **form UI** is retired (see `docs/NORTHSTAR.md`, "What died with v0.1").

## v2 — Chat-first re-architecture (active)

Executable plan: `plans/2026-07-05_v2-chat-first-rearchitecture.md` (T0–T6).

- **T0 — Baseline protection + north-star docs.** Tag v0.1, re-point NORTHSTAR/PRODUCT/ROADMAP/ARCHITECTURE.
- **T1 — LLM provider layer (offline).** Port of the HysysCompanion pattern: `ApiClient`/`ConversationBuilder` protocol, OpenAI Chat/Responses + Antigravity + Copilot adapters, Codex/Copilot subscription OAuth, honest model catalog, headers→settings→default resolver. Anthropic/openrouter remain honest-empty slots.
- **T2 — Agent runtime + tool belt + approval service (offline).** De-Chainlit'd agent loop as an async event generator; allowlisted byte-capped tools over the v0.1 adapters plus new solver-diagnostics and run-monitor tools; server-minted single-use approval tokens (human-click only); injection-corpus test suite; runner glob fix + PVT companion copy.
- **T3 — Chat API spine + license probe.** SSE chat endpoint, session history, provider/OAuth routes; first real `opi.exe` run decides the demo path (real OLGA vs fake-OLGA fallback — either outcome is evidence).
- **T4 — Chat-first frontend swap.** ChatView/ApprovalCard/EvidenceRail/ProviderPanel/EnvDrawer in Evidence Editorial; the six form panes are deleted in the same commit that ships the working chat; marker tests re-assert the no-gradient/no-blur bans.
- **T5 — North-star demo (user participation).** Real provider OAuth, then one conversation: NL setup → human approval click → run → patrol progress in chat → analysis → troubleshooting on a failing case.
- **T6 — Matrix, packaging addendum, handoff.** pip-only LLM layer keeps the PyInstaller story; Windows-form detection globs noted; HANDOFF refreshed.

## v2.1+ outlook (not committed)

- Multi-run scheduled patrol (periodic sweeps + anomaly alerts on fresh results).
- Anthropic / OpenRouter provider backends in the existing slots.
- OPC live control QA on a Windows host (read first, write behind the same approval-token contract).
- Windows-host binary packaging run per `docs/PACKAGING.md`.
- `.ppl` comparison, Excel export, `.out`/`.opi` deep parsing (deferred-by-demand from v0.1).
