# OLGA Workbench — Design Contract

Source of truth for the workbench visual system. Ported from the approved
clickable prototype (todo 4, owner "좋아, 진행." on v7) with prototype-only
details removed. All sample values in examples are invented (`demo_*`).

Implemented in: `frontend/src/styles/base.css` (tokens, themes, motion),
`frontend/src/styles/primitives.css` + `frontend/src/ui/` (primitives),
`frontend/src/styles/motion.css` (Terminalcore stepped motion, pixel icon paint),
`frontend/src/appearance.ts` (theme/motion preferences),
`frontend/src/ui/PixelIcon.tsx` (pixel symbol set),
`frontend/src/formatUnit.mjs` (display unit labels).

## 1. Fonts

Product ships three self-hosted font files (Tauri `default-src 'self'` CSP
intact, no remote fetch), all in `frontend/public/fonts` with their licences:

- **Meslo LGS NF** (`MesloLGSNF-Regular.woff2` and `MesloLGSNF-Bold.woff2`,
  Latin subset, Apache 2.0 with the MIT Nerd Fonts patch; licences in
  `Meslo-LICENSE.txt` and `NerdFonts-LICENSE.txt`): body text, headings,
  labels, figures, codes, file names, buttons and the status bar.
- **Pretendard Variable** (`PretendardVariable.woff2`, 100–900, OFL): all
  Hangul, and display type (`--font-display`).

The full Nerd Font TTF (`MesloLGSNerdFontMono-Regular.ttf`) is no longer in
the app bundle; it lives in `assets/fonts/` for the README video and the
cover script only.

Stacks: `--font-ui: "Meslo LGS NF", "Pretendard Variable", Pretendard,
"Noto Sans KR", "Malgun Gothic", ui-monospace, Consolas, monospace`;
`--font-mono: "Meslo LGS NF", ui-monospace, "SFMono-Regular", Menlo,
Consolas, "Pretendard Variable", monospace`; `--font-display: "Pretendard
Variable", …, sans-serif`. Meslo has no Hangul, so under `:root:lang(ko)`
`--font-ui` is Pretendard first (mono stays for numbers, codes and file
names, with Hangul falling back to Pretendard). Weights above 400 render as
the Bold file; `font-synthesis: none` forbids fake bold.

Mono carries body text, the technical labels (pane index chips, section tags,
coordinates), numbers with units, variable codes (`PT`, `HOL`, …), the run
console, `kbd`, timestamps and file names. `font-variant-numeric:
tabular-nums` applies to numbers, units and identifiers. Uppercase mono
labels are ≤ 3 words, ≥ 12 px, tracked `--track-label` (0.08em). In Korean
(`:lang(ko)`) the listed label classes use letter-spacing 0. Inline mono
renders at `0.93em` of its context, never below the minimum.

## 2. Terminalcore theme (2026-11)

The owner's own brand, `woojin-go-terminalcore`, applied **static only**: the
Tokyo Night palette, Meslo + Pretendard, square corners, 2 px frames, stepped
motion. It replaces the 2026-10-30 neo-brutal lime / magenta theme. There is no
grid lens, text decoding, RGB offset, marquee, scanline, glow, blur, gradient
(one exception below) or soft shadow, and nothing blinks, flickers, strobes or
glitches at any motion level.

Bare `:root` holds Day (`color-scheme: light`); `@media (prefers-color-scheme:
dark) { :root:not([data-theme="light"]) }` and `:root[data-theme="dark"]` hold
Night; `:root[data-theme="light"]` is explicit Day. The app follows the OS
scheme by default; Settings › Display › Theme offers System / Light / Dark
(`olga-companion.theme.v1`) and overrides it through `data-theme`, stamped on
`<html>` before first paint (`initAppearance`). Every colour is a token. At
most four colour families appear in a view: blue, green, cyan and red (ochre
only for warnings).

Roles keep their names. `--select`, `--accent` and `--signal` are the signal
blue (text on a blue fill is `--on-select`, `--accent-ink`, `--signal-ink`);
`--accent-2` is the phosphor green (text on it `--accent-2-ink`); `--focus` is
the focus ring (blue in Day, cyan in Night). `--edge` is the 2 px compartment
rule, `--hairline` the 1 px control border (3:1 or better), `--hairline-soft`
a quiet divider. Status text is `--pass --warn --fail --info`, always paired
with an icon or word. The user's chat bubble is a flat `--bubble-user` wash with
a 2 px `--accent` frame.

Day: `--bg #e1e2e7`, `--bg-deep #d0d5e3`, `--panel/--raised #eceef3`,
`--panel-2 #e1e2e7`, `--ink #1f2335`, `--ink-2 #343b58`, `--mute #4c5585`,
`--select/--accent/--signal/--focus #2459c9` with `--on-select #fbfcff`,
`--accent-2/--pass #3d6b1f`, warn `#7a5200`, fail `#c0174a`, info `#006a8e`,
`--edge #3760bf`, `--hairline #5d6aa3`, `--hairline-soft #b6bdd3`.

Night: `--bg #16161e`, `--bg-deep #101018`, `--panel/--raised #1a1b26`,
`--panel-2 #16161e`, `--ink #c0caf5`, `--ink-2 #a9b1d6`, `--mute #8089b3`,
`--select/--accent/--signal #7aa2f7` with `--on-select #16161e`,
`--accent-2/--pass #9ece6a`, warn `#e0af68`, fail `#f7768e`, info and `--focus`
`#7dcfff`, `--edge` and `--hairline #636c99` (one step brighter than the kit's
`#565f89`, which is 2.76:1 on panels), `--hairline-soft #292e42`.

Series `--s1..--s5` (and `--pipe-1..7`, `--series-1`): Day `#2459c9 #b15c00
#3d6b1f #9854f1 #1f2335`, Night `#7aa2f7 #ff9e64 #9ece6a #bb9af7 #c0caf5`;
the plot film is `#eceef3` / `#101018`. Components read `var(--s1..s5)`; no
hex literal lives in component code (`BrandMark.tsx` keeps token fallbacks).

Shape. Radius 0 everywhere (`--r-*` are all 0), 2 px compartment rules and
frames, 3 px section rule token `--bw-rule`. Floating layers get a 1 px `--ink`
ring (`--elev-pop`), never a shadow; the pressed state is a hard 2 px inset.
Pane headers (Explorer, AI assistant) are the kit's inverse title bar: `--ink`
fill, `--on-ink-body` text, a 2 px `--select` rule, an inverted index chip
(`01` Explorer, `02` centre tabs, `03` dock, `04` bottom panel; decorative,
`aria-hidden`) and a focus ring in `--on-ink-body`. Vertical 2 px rules are the
only side borders past 1 px (shell compartments); cards never carry a status
stripe. The one gradient is `--plot-grid`, the kit's hard-stop 32 px grid with
160 px majors, used on the flowpath geometry plot only.

Measured (lowest over bg, panel, panel-2, raised), Day / Night: ink 12.02 /
10.59, ink-2 8.49 / 8.10, mute 5.51 / 5.00, accent 4.85 / 6.79, accent-2 4.89 /
9.35, warn 5.35 / 8.55, fail 4.69 / 6.46, info 4.70 / 9.96, focus 4.85 / 9.96,
hairline 4.00 / 3.37, edge 4.52 / 3.37; on-select/select 6.12 / 7.14,
accent-ink/accent 6.12 / 7.14. Series on the film: Day ≥ 3.71, Night ≥ 7.52.
Tests pin the values and floors (`neo-theme`, `legibility-contrast`,
`design-tokens`, `terminalcore-theme`). Full table:
`.litclaude/evidence/terminalcore-rebrand/member-A.md`.

## 3. Scale, density and contrast

Tokens `--fs-xs 12 · --fs-s 12 · --fs-m 13 · --fs-l 14 ·
--fs-xl 17 · --fs-2xl 20` at 100 % (one step below the earlier 12–24 ladder;
see the 2026-10-30 revision). `--fs-xs` and `--fs-s` are the same 12 px step:
dense labels and the floor share one size, and the shell base is not raised.
Body and chat 13, UI labels/tabs/fact captions
12, mono values 12+ with tabular-nums; **nothing renders below 12 px at
100 %**. Every font size in the stylesheets is a `--fs-*` token or
`calc(N px * var(--ui-scale))`; no raw px font sizes remain.
Line-height 1.5 prose, 1.35 dense rows. Weights 400 body, 500 interactive /
tab labels, 600 headings + selected, 700 app mark only.

Spacing steps `--sp-1 2 · --sp-2 6 · --sp-3 12 … --sp-10 40` (compact; the
comfortable density restores 4 / 8 for the first two). Density tokens
`--ctl-h 32` and `--tgt`: **compact is the default** (`--tgt 32 px`, above the
WCAG 2.2 AA 24 px floor); `data-density="comfortable"` restores 44 px
targets. `initAppearance` always stamps `data-density` on the root.

UI scale: one root variable `--ui-scale` (`data-ui-scale` 80–130 on the root,
set from Settings, stored under `olga-companion.ui-scale.v1`) multiplies the
type, spacing and control tokens. Panes, sashes and breakpoints stay in CSS
px, so pointer maths is unchanged; CSS `zoom` is not used. At 80–90 % text may
sit below the 12 px floor by the user's choice.

Elevation tokens are `none` or the 1 px ink ring (flat law). Selected state is
carried by `--select` fills with `--on-select` text (≥ 6:1 both themes),
a 2 px bottom bar (tabs) or an inset `--select` ring — never a side stripe
wider than 1 px, never a decorative colour rail.

## 4. Charts and topology

Trend/Profile SVGs size in real px from the measured container
(ResizeObserver, no viewBox shrink): 12 px ticks, 13 px axis titles with
units, 5–7 nice deduped ticks per axis, 2 px series, square end markers
with value labels, legend chip above the plot, 208 px variable picker.
Topology: square 2 px nodes with inverse type strips, 2 px edges,
`--ink` 2 px selection outline, wrap layout under ~1100 px map
width, inspector one click away. Approval card: 2 px `--ink` border,
uppercase heading, reviewed-inputs table scrolls inside,
action row sticky — header, untouched-line, expiry and both buttons
always visible.

## 5. Units, keyboard, IA

Units render display-only through `formatUnit`: `m3/s`, `Pa`, `°C`, `bar`,
`kg/s`, `-` for dimensionless, with canonical casing (`kPa`, `MPa`,
`L/s`). Raw OLGA codes stay unchanged in storage, search indexes and the
approval card — reviewed inputs render as given. Axis titles and readouts
always carry units; variable codes stay English in ko mode. Same regions;
≤760 px stacked tabs; no body h-scroll at 1024/1280/1920; chat opens
scrolled to the approval card; Problems shows 2 findings that select map
nodes.

Keyboard map (all bindings dispatch through `shell/keymap.ts`; Run
entries open the Run preview only and never approve or start a run):

| Keys | Action |
| --- | --- |
| `Ctrl/⌘+1` | Go to Case |
| `Ctrl/⌘+2` | Go to Results |
| `Ctrl/⌘+3` | Go to Run |
| `Ctrl/⌘+4` | Go to Settings |
| `Ctrl/⌘+J` | Toggle chat dock |
| ``Ctrl+` `` | Toggle bottom panel |
| `F5` | Preview run (never executes) |
| `?` | Shortcut map |
| `Ctrl/⌘+K` | Command palette |
| `Esc` | Close palette / dialogs |
| `Ctrl+Enter` | Send (chat composer) |

The palette (`Ctrl/⌘+K`, `ui/CommandPalette`) lists 14 commands:
Case / Results / Run / Settings, dock and panel toggles, Validate,
Preview run, Open run, palette itself, theme toggle, language switch,
shortcut map, and the simulation guide (opens the dock and expands the
collapsed guide). Labels resolve through the `shell.cmd*` dictionary keys;
typing surfaces keep their keys (only the palette opens while typing).

## 6. Motion (static Terminalcore)

Still and exact. Chrome does not move: hover changes colour only (`--lift` is
0). CSS + Web Animations + View Transitions APIs only, feature-detected with
instant fallback. Only `transform`/`opacity` animate (`clip-path` for the
entrance wipe), so there is no layout shift.

Tokens (no raw durations), all easing `steps(3, end)`: `--d-ui 120ms`
(`--ease-ui`), `--d-enter 240ms` (`--ease-enter`), `--d-exit 100ms`
(`--ease-exit`), `--d-snap 80ms` (`--ease-snap`); the aliases `--ease-out`,
`--ease-emphasized`, `--dur-fast 80ms` and `--dur-normal 240ms` follow. No
`cubic-bezier` or smooth timing keyword appears in any stylesheet.

Settings › Motion (모션): Off / Subtle / Full, plus System (`data-motion` on
`:root`, `olga-companion.motion.v1`, persisted like the UI scale). With no
stored choice the OS decides: `prefers-reduced-motion: reduce` starts at Off,
anything else at Subtle (the default). An explicit choice wins. A stored
"reduced" from the earlier setting reads as Subtle. Three tokens carry the
presets on `:root`: `--mo` (duration multiplier 0 / .7 / 1), `--mo-move`
(distance of rises 0 / .4 / 1) and `--fx` (0 / 0 / 1). Off also cancels every
transition and animation (`html[data-motion="off"]` and OS reduced motion).

Full is Subtle plus stepped transitions only: the entrance rise of pane
headers, rail items and Explorer rows, the new step chevron wipe, the view
content wipe (`steps(3, end)`, 160 ms), the stepped theme-toggle view
transition, rolling inspector numbers (`steps(3,end)`) and trend lines drawing
in. The approval card, in Full, may slide in, collapse on reject, wipe the
approve control and stamp (one-shot scale); Subtle and Off show that end state
with no animation. Hover rules exclude `.approval-card`.

Removed for good (a test pins each absence): label scrambling (the component and its
frame generator are deleted), the RGB-offset glitch, the tab-edge flicker, scan sweeps, the
strobe stamp, the run-state pulse loop, the heartbeat and node pulses,
the loader breathing, the theme power-on wash, marching topology edges and the
topology scan. Loops allowed are real loading states only, each stepped and
still under reduced motion: the pixel loader (Full only), the skeleton sweep
and the update progress bar's indeterminate sweep. The sash live size label
(`W 316 PX` / `H 168 PX` on hover, focus and drag) is information, so it shows
in Subtle and Full and is hidden in Off; it is `aria-hidden` and never animated.

## 7. Icons and primitives

Pixel symbol set (`ui/PixelIcon.tsx`): 34 self-drawn symbols on a 12×12
grid, drawn as `<rect>` runs only and painted with `currentColor` and
`shape-rendering: crispEdges` (case, edit, validate, run, results, chat,
settings, fluid, warning, ok, folder, file, graph, export, collapse, grip,
chevron, close, send, node, search, sun, moon, mark, plus, minus, bar, cross,
and the topology kinds pipe, source, sink, valve, riser, separator). `<PixelIcon name size>`
takes the pixel size at 100 % scale (24 = two px per cell) and follows
`--ui-scale`; decorative by default (`aria-hidden`), named when `label` is
passed. In use: the activity rail, step bar (done mark), pane headers and
collapse buttons, Explorer rows (file, fluid, graph by suffix), the
Problems rows, the title-bar actions and theme toggle. Topology nodes draw their kind symbol inside the SVG with `PixelIconInSvg`
(no raster image). Technical decor, static in every preset and always
`aria-hidden`: `ui/FrameDecor` puts 1 px ruler lines along the top and left edges and
crosshair marks (two 1 px bars) in the corners of the topology and chart frames, and the topology
frame carries a live `X 0312 · Y 0118` pointer readout in the mono face. The title-bar barcode strip
stays in the DOM but is not painted (a fake barcode is not a real readout). The 3D renders in
`frontend/public/icons/` and `ui/Icon3D.tsx` remain for artifact use but no
shell surface places them.

Primitives (`frontend/src/ui/`, styles in `primitives.css`): Tabs, Segmented,
Field, Select, Table, IconButton, Toolbar, Panel, Badge, Kbd, Menu/Popover,
CommandPalette. ARIA: `tablist`/`tab`/`tabpanel` with arrow-key roving,
`radiogroup` for Segmented, `menu`/`menuitem` with arrows/Home/End/Esc,
`combobox`+`listbox` with `aria-activedescendant` for the palette.
Focus-visible rings come from the base token rule. Every size and duration
reads a token; no raw font sizes in new CSS. Existing `Button`,
`OperationStatus`, `Receipt`, `Skeleton`, `ActivityLoader` keep working.

## Legibility revision (2026-10-28)

Historical: the values below are the phosphor / drafting-film tokens that the
Terminalcore theme (section 2) replaced; the floors (12 px, 4.5:1, 3:1) stand.

Owner verdict on the dark build (verbatim): "visual 적으로, 시인성이 너무
떨어지지 않는가? 해당 내용도 수정에 반영해주고. 바로 간다."

Response: dark body/UI text is now neutral warm off-white
(`--ink #e9e6dd`, `--ink-2 #cfccc5`, `--mute #97a097`) with phosphor green
kept as accent only (`--select`); light keeps the drafting-film look with
darkened `--ink-2`/`--mute`. Type floor 12 px (`--fs-2xs` removed); labels,
tabs and fact captions 13; body/chat 14; mono values 13+ tabular-nums.
Panel headers are raised surfaces with a 2 px accent rule, not saturated
blocks. Text on any filled accent reaches ≥ 4.5:1 via `--on-select`.
Measured audit: 0 nodes below 12 px, 0 contrast fails, 0 primary-text
fails, dark green body-text share ≈ 0 on Case / Results (plotted fixture) /
Run (preview shown) / Settings, both themes, 1280 and 1920. Full evidence:
`.litclaude/evidence/pro-engineering-ui/legibility.md`.

## Scale and density revision (2026-10-30)

Owner feedback (verbatim, on the installed PVT build): "글자가 전체 앱에 너무
크고, 각 side가 size adjustable 하지 않아. 그리고 조작성도 불편하고. 세팅
앱에는 앱에서 보여지는 글자 크기 등을 조절할 수 있는 공간이 없어."

Response: the default type ladder drops one step (12 · 12 · 13 · 14 · 17 · 20);
Settings gains "글자 크기 / 화면 배율" (en "Text size / UI scale") with
80/90/100/110/120/130 % that applies live and persists; compact density
(32 px targets, 2/6 px spacing) is now the default and comfortable keeps 44 px.
The earlier rule that both densities keep 44 px targets is superseded by this
owner request; 32 px stays above the WCAG 2.2 AA minimum (24 px).
Colours are unchanged. The status bar height is `max(26px, 26px × scale)` so
its hit area holds at 80 %.

## AI dock and Full-level transitions (2026-10-30, revised 2026-11)

Adds the dock's type and live draft, the label rules, the frame symbols, the
Full-level stepped transitions, and the sound policy. Earlier sections
stand; two lines in sections 6 and 7 were corrected to match the code (the
tab view transition is gone, the symbol set has 34 members).

### Chat type

Dock text follows the UI scale and sits on tokens. `.bubble` and the composer
textarea use `--fs-m` (13 px at 100 %), and the code inside a message uses
`--fs-s`. Message prose is line-height 1.5. The composer textarea no longer
uses `--fs-l`. The draft toggle summary and note are `--fs-s` (12 px, the
floor); the draft body is `--fs-s` at line-height 1.5. Message table cells stay
at `--fs-s`.

### Live draft

While a turn runs the dock may show the answer as it is written.

- Content: answer text only. Reasoning is never sent as a draft.
- Display: a closed `<details class="draft-toggle">` appears once the first
  draft text arrives and only while the turn is busy. Summary "작성 중인 답변
  보기" / "Show answer in progress"; open, it shows the note "초안 — 확정 아님" /
  "Draft, not final" above plain text in a focusable, self-scrolling region
  (`aria-live="off"`, capped at 160 px).
- Not persisted: the draft is a display-only event. It never enters history, and
  it clears on the final text, done, error, stop, a tool call or an approval
  request. After `done` only the final assistant bubble remains.
- Redaction: each delta passes the same secret filter as stored text, and an
  unfinished trailing token (or `Bearer` plus a partial token) is held back
  until it completes, so a secret split across chunks is not shown.
- Wait labels: two distinct phases before any text. "다른 답변이 끝나기를 기다리는
  중" / "Waiting for the previous answer to finish" when another turn holds the
  session; "모델 응답 기다리는 중" / "Waiting for the model" once the model call
  begins. Every activity phase label is localized, with a localized elapsed
  line.

### Labels

Uppercase and kicker labels: letter-spacing `--track-label` (0.08em), and 0 under
`:lang(ko)`. Dense rows (pane head, Explorer name and meta, step name, tabs)
use line-height 1.35; body prose uses 1.5. Values (file and variable names,
sample counts) use `--ink`; metadata (extension, size, unit) uses `--mute`.
A selected Explorer name uses `--on-select`. Shell type is not raised: the
`--fs-xs` and `--fs-s` step stays 12 px.

### Symbols

`PixelIcon` adds `plus`, `minus`, `bar` and `cross` (12×12 rect runs, like the
rest). `ui/PaneDecor` draws four corner marks on the Explorer, centre, dock and
bottom panel frames; a `bar` separator sits between a pane title and its
actions, and after the first cell in the step bar and in shared table heads.
All of it is `aria-hidden`, `pointer-events: none`, has no text node, never
animates, and is hidden at 1100 px and below (the nodes stay in the DOM).

### Full-level transitions

All under `html[data-motion="full"]` (`--fx = 1`). Off and Subtle show none of
them at rest or in motion. There is no flash content, so no flash limits apply.

- Stepped wipe: on a centre view change the content children move 6 px into
  place over 160 ms in `steps(3, end)`. Transform only; no clip-path or
  `will-change`. The Results columns do not wipe.
- Pixel loader: a 12×12 solid block steps 4 px in `steps(3, end)` beside the
  chat activity label (800 ms loop); absent in Off and under OS reduced motion.
  Other motion settings keep the still beacon square.
- View switching: no view transition. `selectView` sets the view directly; the
  theme toggle uses a stepped reveal (Full only).
- Motion guards: hover does not apply to `.approve`,
  `.ui-button-primary`, `.wb-btn-primary`, `.run-go`, `[data-busy]` (busy
  buttons set it) or anything inside `.approval-card`.

### Sound policy

Optional cues, synthesized in the browser; there are no audio files, no
dependency and no CSP change.

- Setting: Settings › Display › Sound, Off / Quiet / Full, default Off, plus a
  Volume slider (0–100, default 60) and a Test sound button. Both persist; the
  slider and the button are disabled while Off. With Off no audio context is
  built. The master level is volume × 0.5, and Quiet is a further ×0.55.
- Cues: nine, each under 250 ms (the longest is 230 ms), all different.
- Unlock: the context starts suspended and is resumed by the first real
  `pointerdown` or `keydown`. A cue before that gesture is dropped, not
  replayed. A hidden document plays nothing.
- Quiet plays outcomes only: validation pass and fail, run finished and run
  failed, chat done, chat error. Full adds the view-switch tick and the sash
  grab and release.
- Never: while typing or streaming (no per-token or per-delta sound),
  `approval_required`, anything in the approval card or its continuation,
  hover or focus, a cancelled run, or a run restored from history. A run cue sounds once, only for a run started in this session.
- Independent of motion: sound reads only its own setting. Motion Off does not
  mute it, and sound Off does not change motion.

## Plan card and table comparison (2026-10-31)

### Plan card

An `action_plan` uses the same approval card: 2 px `--ink` border, uppercase
heading, reviewed inputs rendered as given, sticky action row. Under the
heading, one row per step. Each row shows the step and the reviewed inputs
for that step (file, composition, model, grid, or the case fields), in the
same grouped rows a single card uses. A bound run says what is not known yet
and that it is chosen and re-checked when that step starts.

Once a result exists, the row shows a state. **Started** means a run has been
launched and may still be going. **Stopped here** is a failed step: the
outcome is known, the step did not complete, and the chain stopped. **Outcome
unknown** is uncertain: the outcome could not be confirmed, and it is not
shown as a definite failure. **Done** and **Not run** mark the steps that
finished and the steps that never started. Failed and uncertain rows take an
`--ink` border. The state label is `--mute` at `--fs-xs` on the card surface,
inside the mute floors in section 2 (Night 5.00, Day 5.51, both above 4.5:1).

### Comparison view

`fluids_compare_tab` draws in the dock and writes nothing. A table lists each
column's mean and maximum relative difference and where the maximum sits.
Under it, a heat strip draws one cell per temperature-pressure bin; the cell
is that bin's maximum. A cell with nothing compared (the reference value is
zero, or the node is missing) is hatched: a flat `--panel-2` fill and a 1 px dashed
`--mute` outline (no stripe gradient). Its title says nothing was compared.

Heat cells are `aria-hidden`. The numbers live in the table and in the
strip's label, set in `--ink`, `--ink-2` and `--mute`. Section 2 measures
those text tokens above 4.5:1 on every surface they sit on. The strip edge
is 1 px `--hairline`. Section 2 measures that hairline at 3.37:1 in Night
and 4.00:1 in Day, above the 3:1 floor for non-text.
