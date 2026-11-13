# OLGA Companion North Star (v2)

OLGA Companion is a chat-first agent app for OLGA flow-assurance work. The user says what they want in natural language — "CO2 파이프라인 케이스 만들어서 검증하고 돌려줘" — and an LLM agent orchestrates the full simulation lifecycle with the OLGA toolkit as its hands: **define → build → configure → validate → check the runner → smoke test → main run → monitor (patrol) → analyze → troubleshoot → report.**

The reference experience is a coding agent driving an OLGA toolkit from a terminal: one conversational surface, the agent doing the file work, the human making the judgement calls. OLGA Companion packages that experience for engineers who will never open a CLI.

## What died with v0.1

The form-based workbench (six panes of path inputs) is retired and must not return:

- **No path typing.** The agent discovers and manages files inside a workspace; users drop files or name them in prose.
- **No raw capability matrix in the user's face.** Capability gates remain fail-closed in the backend and are visible in a quiet environment drawer; the agent explains gaps in natural language when they matter.

## Provider independence

The LLM layer is provider-agnostic by construction: a single agent loop over an `ApiClient`/`ConversationBuilder` protocol with per-provider adapters and subscription-OAuth auth. OpenAI (Codex), GitHub Copilot, Antigravity (Gemini), xAI (Grok) and API-key connections are wired; other providers plug into the same slots. The model catalog is honest: a provider with no wired backend shows an empty list, never fake options.

## Primary users

- Flow-assurance engineers preparing and running OLGA cases.
- Simulation specialists reviewing `.genkey`, `.mfl`, `.tab`, `.tpl`, `.ppl`, and solver output.
- Project engineers who need auditable PASS/FAIL evidence without touching fragile simulator files.

## Product promise

1. **Converse** — the entire lifecycle is driven from one chat surface; artifacts (validation reports, topology, plots, judgements) render inline as evidence.
2. **Build safely** — the agent edits only sandbox copies via allowlisted toolkit adapters; owner files are never mutated.
3. **Run only with human approval** — executing a simulation (and any future OPC write) requires a human click on the exact server-rendered pending action. The server claims that action once and keeps its short-lived capability entirely out of UI text, chat history, and provider context. The agent cannot approve itself; its tool schemas have no approval intent field.
4. **Patrol** — while a run is live, progress from the growing `.out` streams into the chat; stalls surface with liveness timeouts.
5. **Troubleshoot** — failed or suspicious runs go through solver diagnostics (convergence, mass error, issue detection) and the agent proposes and applies fixes as new sandbox copies.
6. **Prove everything** — the app must never treat LLM/natural-language interpretation as simulator truth. Every engineering claim needs file, parser, validation, or result evidence.

## Non-promises and overclaim boundaries

- No live-run claim until an OLGA executable is detected and validated; no Multiflash claim beyond file preparation until a real CLI is verified; no OPC-write claim until the Windows gate conditions pass live QA.
- Untrusted file content (cases, tables, logs) is data, never instructions: nothing read from a file may elevate the agent's permissions.
- The app never silently mutates user-owned files, and never ships a provider option that has no working backend.
