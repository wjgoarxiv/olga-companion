---
colors:
  ink: "#111111"
  canvas: "#ffffff"
  soft-cloud: "#f5f5f5"
  hairline: "#cacacb"
  hairline-soft: "#e5e5e5"
  charcoal: "#39393b"
  mute: "#707072"
  stone: "#9e9ea0"
  fail: "#d30005"
  fail-deep: "#780700"
  pass: "#007d48"
  info: "#1151ff"
  on-primary: "#ffffff"
typography:
  display-masthead: "clamp(2.5rem, 6vw, 5rem)/0.92 700 uppercase, letter-spacing -0.02em"
  heading-xl: "24px/1.2 700 uppercase, letter-spacing 0"
  heading-md: "16px/1.5 700"
  body-md: "16px/1.5 400"
  body-strong: "16px/1.5 600"
  button-md: "15px/1.4 600"
  caption-md: "14px/1.5 500"
  caption-sm: "12px/1.5 500"
  mono-evidence: "13px/1.55 400 ui-monospace"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  section: "48px"
rounded:
  none: "0px"
  input: "24px"
  pill: "30px"
  full: "9999px"
components:
  button-primary: "bg ink, text on-primary, rounded pill, 44px height, padding 0 28px"
  button-primary-disabled: "bg soft-cloud, text stone, rounded pill"
  status-pass: "text pass, no background, body-strong"
  status-fail: "text fail, no background, body-strong"
  capability-row: "hairline-top row; name body-strong ink; state caption-sm (pass green when Enabled, mute when Gated); reason caption-md mute"
  evidence-block: "bg soft-cloud, rounded none, mono-evidence charcoal, hairline border, max-height scroll"
  section-header: "heading-xl ink uppercase above hairline divider, section rhythm 48px"
---

# OLGA Companion — Evidence Editorial Design System

One idea: **the evidence speaks, the chrome doesn't.** Plots, validation transcripts, and judgement cards carry all visual energy on a flat white bench; the chrome is ink typography, hairline rules, and pill actions. Adapted from a user-supplied Nike-commerce system extraction; the display tier is the masthead only, and the catalog's "sale red" becomes FAIL red.

## Colors

- `{colors.ink}` `#111111` — the only "brand color": masthead, headings, primary pills, body text, active states.
- `{colors.canvas}` `#ffffff` — page and card surface. Cards are regions of the page, not floating objects.
- `{colors.soft-cloud}` `#f5f5f5` — the stage: evidence blocks (`pre`), inputs, secondary pills, plot mats.
- `{colors.hairline}` `#cacacb` / `{colors.hairline-soft}` `#e5e5e5` — 1px rules; the only depth in the system (plus one inset hairline under sticky strips if ever needed).
- Semantic (text-only, never backgrounds): `{colors.pass}` `#007d48` (PASSED/Enabled/ok), `{colors.fail}` `#d30005` (FAILED/errors), `{colors.info}` `#1151ff` (download links). Contrast on canvas: pass 5.1:1, fail 5.9:1, info 6.5:1, mute 5.3:1 — all AA.
- Q3 (2026-07-05) relaxed the flat law: **gradients, glassmorphism, and soft shadows are now allowed** for a cutting-edge finish — used deliberately and within a **paint budget** (they originally caused compositor stalls at deep scroll on Windows Chrome, so every effect is QA'd there and pulled back if it stalls). Still banned: **amber** for gated states (gated = `{colors.mute}` text — designed state, not alarm), and **dark mode**.

## Typography

UI face is **self-hosted Pretendard** (a modern KR+Latin variable font, OFL, bundled in `/public/fonts` — self-hosted, never a CDN, so the Tauri self-only CSP holds), with `"Helvetica Neue", Helvetica, Arial, sans-serif` as the fallback and grayscale font-smoothing on; evidence output stays in `ui-monospace, "Cascadia Mono", Consolas, monospace`. Extreme two-tier contrast: `{typography.display-masthead}` for the app masthead, then a quiet 12–16px tier for everything else — section headers are `{typography.heading-xl}` (24px uppercase), never a middle ground. Fixed rem scale below the masthead (product register: no fluid type in the working tiers).

## Layout

8px base, max width 1180px. The v2 shell is a **fixed-viewport app**, not a document that scrolls: a `100dvh` grid of compact top bar / single-scroll timeline / sticky composer. The masthead is demoted to a compact top-bar wordmark (uppercase, ~20px) with the provider/model pickers and the environment chip as quiet chrome beside it — the display tier survives as identity, not as a permanent hero billboard. The **timeline is the only scroll region** (no nested page + pane scroll). A tool call and the evidence it produced render as **one grouped, collapsible unit** — the evidence directly under the call that produced it (regression-locked; the orphaned-results bug is design-relevant history). Under 720px the chrome wraps under the wordmark; the conversation stays the dominant region (there is no sidebar to bury it). The `{colors.hairline}` rule is the only divider — no decorative bands, no drop shadows.

## Components

- **Pills only**: `{components.button-primary}` for every submit; disabled = `{components.button-primary-disabled}` (no opacity tricks). Icon-less, text-label pills. No second button shape.
- **Inputs**: `{colors.soft-cloud}` fill, `{rounded.input}`, no border at rest; focus = 2px `{colors.ink}` border (the system's only focus treatment).
- **Status lines**: text-only verdicts — `{components.status-pass}` / `{components.status-fail}`; no filled badges, no pill backgrounds for state.
- **Capability gates**: `{components.capability-row}` list (hairline rows, not cards) — Enabled in pass green, Gated in mute with its reason inline.
- **Evidence blocks**: `{components.evidence-block}` — monospace on soft-cloud, the "product photography" of this app.
- **Judgement/metadata dl**: two-column, `dt` `{colors.mute}` caption-md, `dd` ink.

## Do / Don't

- Do keep FAIL red and PASS green as the only chromatic events per viewport.
- Do keep every card flat: radius 0, border 1px hairline or nothing, shadow never.
- Gradients / glass / soft shadows are allowed (Q3) but stay on a **paint budget** — verify no deep-scroll compositor stall; don't reintroduce the dark-glow theme or dark mode.
- Don't use display type below the masthead; don't uppercase anything except masthead + section headers.
