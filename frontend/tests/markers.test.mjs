import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readSessionSource } from './session-source.mjs';

const read = (p) => readFile(new URL(p, import.meta.url), 'utf8');
const readCss = async () => {
  const root = await read('../src/styles.css');
  const imports = [...root.matchAll(/@import ['"](.+)['"];/g)];
  const imported = await Promise.all(imports.map((m) => read(`../src/${m[1]}`)));
  return [root, ...imported].join('\n');
};

test('chat dock mounts ChatView; the v0.1 form panes stay gone', async () => {
  const app = await read('../src/App.tsx');
  const dock = await read('../src/shell/ChatDockView.tsx');
  const chat = await read('../src/ChatView.tsx');
  const stream = await read('../src/useChatStream.ts');
  assert.match(app, /useChatController/, 'the orchestrator keeps chat runtime control');
  assert.match(app, /useRuntimeConnection/, 'the orchestrator keeps runtime ownership');
  assert.match(dock, /<ChatView\b/);
  assert.match(chat, /className="chat"|Conversation/);
  assert.match(stream, /streamChat/);
  // The v0.1 form panes are gone — importing any of them must fail the build,
  // so assert they are not referenced.
  for (const pane of ['FluidPvtPane', 'RunPane', 'ResultsPane', 'EvaluatePane', 'ReportsPane']) {
    assert.doesNotMatch(app, new RegExp(pane), `${pane} must stay torn down`);
  }
});

test('title-bar brand is an engineered two-tier lockup that returns home', async () => {
  const bar = await read('../src/shell/TitleBar.tsx');
  const css = await readCss();

  assert.match(bar, /<button[^>]*className="wordmark"[^>]*aria-label=\{t\('app\.homeAria'\)\}/s);
  assert.match(bar, /className="wordmark-primary" aria-hidden="true">OLGA<\/span>/);
  assert.match(bar, /className="wordmark-secondary" aria-hidden="true">COMPANION<\/span>/);
  assert.match(bar, /onClick=\{onHome\}/, 'the brand returns to the Explorer home');
  assert.match(css, /\.wordmark-primary\s*\{[^}]*font-family:\s*var\(--font-ui\)[^}]*font-size:\s*var\(--fs-xl\)[^}]*font-weight:\s*900[^}]*scaleX\(1\.12\)[^}]*text-rendering:\s*geometricPrecision/s);
  assert.doesNotMatch(css, /\.wordmark-index\b/);
  assert.match(css, /\.wordmark-secondary\s*\{[^}]*font-size:\s*var\(--fs-xs\)[^}]*letter-spacing:\s*var\(--track-label\)[^}]*text-transform:\s*uppercase/s);
  assert.doesNotMatch(css, /\.wordmark::(?:before|after)/, 'the product lockup no longer carries an ornamental blue datum');
  assert.doesNotMatch(css, /url\(["']?https?:/, 'the wordmark must not require a remote font');
  assert.doesNotMatch(css.match(/\.wordmark\s*\{[^}]*\}/s)?.[0] ?? '', /Monument/, 'the product wordmark remains independent of the creator-credit font');
});

test('approval is a human-only act showing the exact action', async () => {
  const [card, ko] = await Promise.all([
    read('../src/ApprovalCard.tsx'),
    read('../src/i18n/ko.ts'),
  ]);
  assert.match(card, /t\('approval\.title'\)/);
  assert.match(ko, /'approval\.title': '승인 필요'/);
  assert.match(card, /cannot approve it for you|human-only|cannot approve/i);
  assert.match(card, /args\.source/);
  const appjs = await read('../src/useChatController.ts');
  // Approval claims a server-stored exact action; no capability enters chat text.
  assert.match(appjs, /session\.executeApproval\([\s\S]*request\.pending_id/);
  assert.doesNotMatch(appjs, /approval_token/);
});

test('SSE client flattens FastAPI 422 detail arrays (v0.1 [object Object] bug)', async () => {
  const s = await readSessionSource(import.meta.url);
  assert.match(s, /flattenDetail/);
  assert.match(s, /Array\.isArray/);
  assert.match(s, /loc/);
  // And no naive detail-to-string that would reproduce "[object Object]".
  assert.doesNotMatch(s, /body\.detail\s*\|\|\s*['"]/);
});

test('theme keeps the ink token and stays motion-safe (brutal roles; paint budget enforced by QA)', async () => {
  const css = await readCss();
  // Ink is the theme anchor: Terminalcore Day ink in light, Night ink in dark;
  // the signal blue stays for selections, not body text.
  assert.match(css, /--ink:\s*#1f2335/);
  assert.match(css, /--ink:\s*#c0caf5/);
  assert.match(css, /--select:\s*#2459c9/);
  assert.match(css, /--select:\s*#7aa2f7/);
  // Q3 relaxed the gradient/blur bans, but motion must stay fully disable-able —
  // reduced-motion is the accessibility floor, and the deep-scroll paint budget
  // is enforced by browser QA (see evidence/uplift-t5.md), not a static rule.
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /animation:\s*none\s*!important/);
  assert.match(css, /--ease-ui:/, 'easings read tokens');
  assert.match(css, /--d-ui:/, 'durations read tokens');
});

test('agent approval card executes the server-bound pending action', async () => {
  const chat = await read('../src/useChatController.ts');
  const tools = await read('../../src/olga_companion/agent/tool_side_effects.py');
  assert.match(chat, /session\.executeApproval\([\s\S]*request\.pending_id,\s*sessions\.sessionId,\s*request\.call_id/);
  assert.match(tools, /action_kind == "sweep_execute"[\s\S]*sweep_id[\s\S]*plan_id/);
  assert.doesNotMatch(chat, /approval_token/);
});

test('empty state activates first-run with clickable starters', async () => {
  const chat = await read('../src/ChatView.tsx');
  assert.match(chat, /EmptyState/);
  const es = await read('../src/EmptyState.tsx');
  assert.match(es, /onPick/);
  assert.match(es, /caseContext/, 'starters still use the active workbench context');
  assert.match(es, /starter-groups/, 'empty Chat groups starters by workflow intent');
  const bar = await read('../src/WorkspaceBar.tsx');
  assert.match(bar, /className="case-context"/, 'the shared case selector keeps the context available');
  const starters = es.match(/prompt:/g) || [];
  assert.ok(starters.length >= 3, 'at least three concrete starter prompts');
});

test('a tool call and its evidence render as one grouped unit (no orphaned evidence)', async () => {
  const chat = await read('../src/ChatView.tsx');
  assert.match(chat, /ToolUnit/);
  // Evidence is folded into the tool item, not a separate sibling timeline kind.
  const timeline = await read('../src/timeline.ts');
  assert.doesNotMatch(timeline, /kind:\s*'evidence'/, 'evidence is merged into the tool unit');
  const tu = await read('../src/ToolUnit.tsx');
  assert.match(tu, /EvidenceBlock/);
});

test('paths are elided to basenames — the app never makes users read absolute paths', async () => {
  const card = await read('../src/ApprovalCard.tsx');
  assert.match(card, /basename/);
  const ev = await read('../src/EvidenceBlock.tsx');
  assert.match(ev, /compactValue|basename/);
});

test('an approval-gated refusal reads as a quiet awaiting state, not a red error', async () => {
  const chat = await read('../src/useChatController.ts');
  assert.match(chat, /approvalCallIds/);
  assert.match(chat, /status:\s*'awaiting-approval'/);
});

test('the UI font is self-hosted (CSP-safe), not a CDN, with grayscale smoothing', async () => {
  const css = await readCss();
  assert.match(css, /@font-face/, 'a bundled @font-face is declared');
  assert.match(css, /Pretendard/);
  // Self-hosted from /public — an absolute /fonts path, never an http(s) CDN URL,
  // so the Tauri default-src 'self' CSP still holds.
  assert.match(css, /src:\s*url\(["']\/fonts\//);
  assert.doesNotMatch(css, /@import\s+["']https?:|url\(["']?https?:/, 'no external font fetch');
  assert.match(css, /-webkit-font-smoothing:\s*antialiased/);
  // The mono face ships the same self-hosted way, with tabular figures for data.
  assert.match(css, /MesloLGSNF-Regular\.woff2/);
  assert.match(css, /font-variant-numeric:\s*tabular-nums/);
});

test('reasoning is surfaced: the runtime emits thinking and the UI renders it', async () => {
  const rt = await read('../../src/olga_companion/agent/runtime.py');
  assert.match(rt, /AgentEvent\("thinking"/);
  const chat = await read('../src/useChatController.ts');
  assert.match(chat, /'thinking'/);
});

test('assistant markdown renders safely (no raw HTML) — the raw-text leak is closed', async () => {
  const chat = await read('../src/ChatView.tsx');
  assert.match(chat, /import Markdown from '\.\/Markdown'/);
  assert.match(chat, /<Markdown text=\{item\.text\}/, 'assistant text goes through the markdown renderer, not a bare string');
  const md = await read('../src/Markdown.tsx');
  // Match actual usage (attr/prop), not the doc-comment that names the ban.
  assert.doesNotMatch(md, /dangerouslySetInnerHTML\s*[=:]/, 'renderer never injects raw HTML');
  const parser = await read('../src/markdownParser.mjs');
  assert.doesNotMatch(parser, /dangerouslySetInnerHTML\s*[=:]/);
  assert.match(parser, /https\?:/, 'links are restricted to http(s) in the parser');
});

test('assistant messages expose copy + retry actions; empty state offers >=6 starters', async () => {
  const controller = await read('../src/useChatController.ts');
  const chat = await read('../src/ChatView.tsx');
  assert.match(chat, /MessageActions/);
  assert.match(controller, /regenerate/, 'retry re-runs the last turn');
  const ma = await read('../src/MessageActions.tsx');
  assert.match(ma, /t\('chat\.copy'\)/);
  assert.match(ma, /t\('chat\.retry'\)/);
  const es = await read('../src/EmptyState.tsx');
  const starters = es.match(/prompt:/g) || [];
  assert.ok(starters.length >= 6, `expected >=6 starter prompts, got ${starters.length}`);
  assert.match(es, /Workspace/, 'starters include workspace-oriented work');
  assert.match(es, /Run/, 'starters include run-oriented work');
  assert.match(es, /Results/, 'starters include results-oriented work');
});

test('home navigation: new-chat control + session switcher rehydrating from history', async () => {
  const controller = await read('../src/useChatController.ts');
  const chat = await read('../src/ChatView.tsx');
  assert.match(chat, /className="new-chat"/, 'a New Chat (home) control exists');
  assert.match(controller, /newChat/);
  assert.match(chat, /SessionMenu/);
  assert.match(controller, /loadSession/);
  const timeline = await read('../src/timeline.ts');
  assert.match(timeline, /rehydrateTimeline/, 'past sessions rehydrate into the timeline');
  const s = await readSessionSource(import.meta.url);
  assert.match(s, /fetchSessions/);
  assert.match(s, /fetchSessionHistory/);
});

test('an in-flight turn can be stopped (AbortController wired to the stream)', async () => {
  const stream = await read('../src/useChatStream.ts');
  const chat = await read('../src/ChatView.tsx');
  assert.match(stream, /new AbortController\(\)/);
  assert.match(stream, /controller\.signal/, 'the abort signal is passed to streamChat');
  assert.match(chat, /className="stop"/, 'a Stop control replaces Send while busy');
  assert.match(stream, /abortRef\.current === controller/);
  assert.match(stream, /controller\.abort\(\)/);
  assert.match(stream, /stopChatResponse\(sessionId\)/, 'Stop response also cancels the server-side assistant stream');
});

test('motion is a token system, fully disabled under reduced-motion', async () => {
  const css = await readCss();
  assert.match(css, /--ease-out:/, 'an easing token exists');
  assert.match(css, /--dur-(fast|normal):/, 'duration tokens exist');
  assert.match(css, /@keyframes rise/, 'purposeful entrance motion');
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
});
