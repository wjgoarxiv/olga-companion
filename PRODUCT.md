# OlgaCopilot — Product Context

## Register

product — a chat-first engineering agent. Design serves the conversation and its evidence; chrome disappears into the work.

## Users & Purpose

Flow-assurance engineers, simulation specialists, and project engineers (see `docs/NORTHSTAR.md`). They open the app mid-task and *talk*: define a case, have the agent build and validate it, approve a run, watch patrol progress, read evidence-backed interpretation. No forms, no path fields. Light theme remains the committed choice — a lab bench for reading dense evidence under office lighting.

## Surface anatomy (v2)

- **ChatView** — the primary surface. Agent text is quiet prose; tool activity renders as compact chips; evidence blocks (validation reports, topology, plots, judgement cards) are the photography and get the visual energy.
- **ApprovalCard** — the one loud moment by design: the server-rendered exact command with Approve/Reject. Approval is a human-only act; the card's clarity is a safety feature, not decoration.
- **EvidenceRail** — session artifacts, flat list, hairline-separated.
- **ProviderPanel** ("AI 공급자 연결") — per-provider connection status and an honest model picker (empty catalog = no picker).
- **EnvDrawer** — capability/environment state, quiet and collapsed by default. Gates are designed states, not alarms; they read neutral, never amber.

## Brand Personality

**Editorial restraint applied to an engineering instrument** — the Evidence Editorial system carries over from v0.1 unchanged in law: ink on canvas, hairline dividers, pill actions, flat zero-shadow surfaces, 8px rhythm, uppercase masthead. Verdicts are the only chromatic events (PASS green `#007d48`, FAIL red `#d30005`), exactly like sale price in a retail catalog: color = signal, never tone.

## Anti-references

- **The v0.1 form workbench of this very app** — six panes of path inputs; the reason v2 exists. Any design that asks a user to type a filesystem path has failed.
- The pre-v0.1 dark theme: navy radial gradients, glassy cards, blur shadows (root cause of real compositor stalls in browser QA).
- SaaS dashboard gradients, hero-metric tiles, glassmorphism, chat-app gimmicks (typing indicators with bounce, avatar bubbles).

## Accessibility & Constraints

- WCAG AA minimum: body text ≥4.5:1, large text ≥3:1 (palette in DESIGN.md).
- No external font/CDN fetches — Tauri CSP is `default-src 'self'`; system Helvetica/Arial stack only.
- `prefers-reduced-motion` honored; motion conveys state only (150–250 ms); streaming text appends without animation tricks.
- **Flat rendering is a performance requirement**: no full-page gradients, no large-radius box-shadows (regression-locked in marker tests; they caused renderer paint failures at deep scroll on Windows Chrome).
- Long transcripts must stay scroll-cheap: evidence `pre` blocks keep bounded max-height and `content-visibility: auto`.
