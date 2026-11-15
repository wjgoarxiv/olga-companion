import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('Given the product lockup, when it is activated, then Explorer home is restored', async () => {
  // Given
  const [bar, app] = await Promise.all([
    read('../src/shell/TitleBar.tsx'),
    read('../src/App.tsx'),
  ]);

  // When / Then
  assert.match(bar, /<button[^>]*className="wordmark"[^>]*aria-label=\{t\('app\.homeAria'\)\}[^>]*onClick=\{onHome\}/s);
  assert.match(bar, /<\/button>/);
  assert.match(app, /onHome=\{\(\) => selectView\('workspace'\)\}/, 'the brand returns to the Explorer home');
});

test('Given selected controls, when state changes, then depth replaces decorative color rails', async () => {
  // Given
  const [base, shell, workspace, results, session, flowpath, run] = await Promise.all([
    read('../src/styles/base.css'),
    read('../src/styles/shell.css'),
    read('../src/styles/workspace.css'),
    read('../src/styles/results.css'),
    read('../src/styles/session-rail.css'),
    read('../src/styles/flowpath-inspector.css'),
    read('../src/styles/run.css'),
  ]);

  // When / Then
  assert.match(base, /--state-inset:/, 'one tactile state token serves selection surfaces');
  for (const css of [workspace, results, session, flowpath]) {
    assert.match(css, /var\(--state-inset\)/);
  }
  // The pressed rail item sits on the sliding solid select block (no inset shadow on top of it).
  assert.match(shell, /\.wb-activity \.ui-iconbutton\[aria-pressed="true"\]\s*\{[^}]*color:\s*var\(--on-select\)/s);
  assert.match(run, /\.run-mode \.ui-segmented-option\[aria-checked="true"\]\s*\{[^}]*box-shadow:\s*inset 0 0 0 1px var\(--accent\),\s*var\(--state-inset\)/s);
  assert.match(results, /\.trend-legend button\[aria-pressed="true"\]\s*\{[^}]*box-shadow:\s*var\(--state-inset\)/s);
  assert.doesNotMatch(shell, /\.nav-item\.active\s*\{[^}]*inset\s+3px\s+0/s);
  assert.doesNotMatch(results, /\.rv-files \.ws-file\.active::before/);
});

test('Given inline technical identifiers, when markdown renders, then a Nerd Font mono stack is used', async () => {
  // Given
  const [base, messages] = await Promise.all([
    read('../src/styles/base.css'),
    read('../src/styles/chat-messages.css'),
  ]);

  // When / Then
  assert.match(base, /font-family:\s*"Meslo LGS NF"/);
  assert.match(base, /MesloLGSNF-Regular\.woff2/);
  assert.match(base, /MesloLGSNF-Bold\.woff2/);
  assert.match(base, /--font-mono:\s*"Meslo LGS NF"/);
  assert.match(messages, /\.md code\s*\{[^}]*var\(--font-mono\)/s);
});

test('Given conversation actions, when the header renders, then new and past chats form one labelled control group', async () => {
  // Given
  const [chat, menu, shell] = await Promise.all([
    read('../src/ChatView.tsx'),
    read('../src/SessionMenu.tsx'),
    read('../src/styles/shell.css'),
  ]);

  // When / Then
  assert.match(chat, /aria-label=\{t\('chat\.conversationActions'\)\}/);
  assert.match(chat, /icon=\{<Plus/);
  assert.match(chat, /aria-label=\{t\('chat\.startNewChat'\)\}/);
  assert.match(menu, /aria-label=\{open \? t\('history\.closeHistory'\) : t\('history\.openHistory'\)\}/);
  assert.match(menu, /event\.key !== 'Escape'/);
  assert.match(menu, /triggerRef\.current\?\.focus\(\)/);
  assert.match(shell, /\.chat-head-actions\s*\{[^}]*border:[^}]*border-radius:\s*var\(--r-surface\)/s);
});

test('Given an unavailable runtime, when the header renders, then recovery stays compact and explicit', async () => {
  // Given
  const [status, css] = await Promise.all([
    read('../src/RuntimeNavStatus.tsx'),
    read('../src/styles/runtime-status.css'),
  ]);

  // When / Then
  assert.match(status, /titleKey:\s*'runtime\.offlineTitle'/);
  assert.match(status, /stateKey:\s*'runtime\.offlineState'/);
  assert.match(status, /aria-label=\{`\$\{t\(presentation\.titleKey\)\}\. \$\{detail\}`\}/);
  assert.match(status, /\{t\('runtime\.retry'\)\}\s*<\/Button>/);
  assert.match(css, /\.runtime-nav-status\s*\{[^}]*width:\s*fit-content[^}]*max-width:/s);
  assert.match(css, /\.runtime-nav-status-label\s*\{[^}]*text-transform:\s*uppercase/s);
});

test('Given runtime diagnostics, when the disclosure is closed, then its purpose remains visible', async () => {
  // Given
  const drawer = await read('../src/EnvDrawer.tsx');

  // When / Then
  assert.match(drawer, /<CircleGauge/);
  assert.match(drawer, /<span className="conn-label">\{t\('env\.systemStatus'\)\}<\/span>/);
  assert.doesNotMatch(drawer, />Diagnostics</);
  assert.match(drawer, /aria-label=\{open \? t\('env\.ariaClose'/);
});

test('Given a narrow viewport, when the shell stacks, then every region keeps its order without horizontal overflow', async () => {
  // Given
  const wb = await read('../src/styles/workbench.css');

  // When / Then
  assert.match(wb, /@media \(max-width: 768px\)[\s\S]*?\.wb-mid\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s);
  assert.match(
    wb,
    /@media \(max-width: 768px\)[\s\S]*?grid-template-areas:\s*"activity"\s*"explorer"\s*"centre"\s*"dock"\s*"panel"/s,
    'stacked regions follow the focus order title bar > activity > explorer > centre > dock > panel',
  );
  assert.match(wb, /\.wb-mid\s*\{[^}]*min-width:\s*0/s);
  assert.match(wb, /\.wb\s*\{[^}]*min-width:\s*0/s);
});

test('Given system status, when it opens, then one flat popover reports sidecar state rather than model state', async () => {
  // Given
  const [status, app, primitives] = await Promise.all([
    read('../src/shell/StatusBar.tsx'),
    read('../src/App.tsx'),
    read('../src/styles/primitives.css'),
  ]);

  // When / Then
  assert.match(status, /operatorDetailText\(t, detail\)/, 'the popover leads with sidecar state');
  assert.match(status, /<Popover open=\{open\} onClose/, 'one popover carries every runtime-state readout');
  assert.match(primitives, /\.ui-popover\s*\{[^}]*border-radius:\s*var\(--r-s\)/s, 'the popover follows the flat brutal law');
  assert.match(app, /<StatusBar[\s\S]*?state=\{runtime\.state\}/, 'the bar feeds the single runtime state');
  assert.doesNotMatch(status, /env-popover|statusbar-model/, 'no second runtime surface survives beside the status item');
});

test('Given operation feedback, when it is rendered, then it uses the shared rounded surface', async () => {
  // Given
  const controls = await read('../src/styles/controls.css');

  // When / Then
  assert.match(controls, /\.operation-status\s*\{[^}]*border-radius:\s*var\(--r-surface\)/s);
});

test('Given a new chat message, when it mounts, then it steps in without blur and respects reduced motion', async () => {
  // Given
  const [chat, messages, responsive] = await Promise.all([
    read('../src/ChatView.tsx'),
    read('../src/styles/chat-messages.css'),
    read('../src/styles/chat-responsive.css'),
  ]);

  // When / Then
  assert.match(chat, /className="msg user"/);
  assert.match(messages, /@keyframes\s+message-resolve\s*\{[^]*?opacity:/s);
  assert.doesNotMatch(messages, /blur\(/, 'Terminalcore has no blur');
  assert.match(messages, /\.msg\s*\{[^}]*animation:\s*message-resolve 240ms var\(--ease-emphasized\)/s);
  assert.match(messages, /--ease-emphasized/, 'the entrance reads the stepped easing token');
  assert.match(messages, /\.bubble\.assistant\s*\{[^}]*border:/s);
  assert.doesNotMatch(messages.match(/\.bubble\.assistant\s*\{[^}]*\}/s)?.[0] ?? '', /box-shadow/, 'the hairline already separates the bubble');
  assert.doesNotMatch(messages.match(/\.msg\s*\{[^}]*\}/s)?.[0] ?? '', /message-resolve[^;]*\b(?:both|forwards)\b/, 'a held fill-mode would leave a permanent animation layer on the text');
  assert.match(responsive, /prefers-reduced-motion:\s*reduce[^]*?animation:\s*none\s*!important/s);
});

test('Given visual QA, when lifecycle components render, then the real assistant and status surfaces are inspectable', async () => {
  const fixture = await read('./lifecycle-visual-fixture.tsx');
  assert.match(fixture, /className="msg assistant"/);
  assert.match(fixture, /<Markdown text=/);
  assert.match(fixture, /<OperationStatus tone="info"/);
});
