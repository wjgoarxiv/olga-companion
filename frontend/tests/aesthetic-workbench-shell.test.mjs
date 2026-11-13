import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('Given the desktop shell, when the header renders, then context and system state have a deliberate hierarchy', async () => {
  const [statusbar, bar, workspaceBar] = await Promise.all([
    read('../src/styles/statusbar.css'),
    read('../src/shell/StatusBar.tsx'),
    read('../src/WorkspaceBar.tsx'),
  ]);

  assert.match(statusbar, /\.wb-status\s*\{[^}]*height:\s*var\(--sb-h\)/s, 'one 24-28px bar carries status');
  assert.match(bar, /wb-status-runtime/, 'OLGA runtime owns the status item');
  assert.match(bar, /t\('status\.aiModel'\)/, 'the model keeps its readout');
  assert.match(bar, /t\('shell\.sidecar'\)/, 'sidecar state stays visible');
  assert.match(bar, /t\('shell\.cmdSwitchLanguage'\)/, 'the locale keeps its readout');
  assert.doesNotMatch(statusbar, /\.wordmark::(?:before|after)/, 'the ornamental blue datum is removed');
  assert.match(workspaceBar, /className="case-context-label">\{t\('status\.caseContext'\)\}/);
  assert.match(workspaceBar, /className="case-context"/);
});

test('Given Chat history, when Chats is toggled, then it opens a folded side rail rather than a dropdown', async () => {
  const [menu, css, rootCss] = await Promise.all([
    read('../src/SessionMenu.tsx'),
    read('../src/styles/session-rail.css'),
    read('../src/styles.css'),
  ]);

  assert.match(menu, /className="session-rail-toggle"/);
  assert.match(menu, /t\('history\.openHistory'\)/);
  assert.match(menu, /t\('history\.closeHistory'\)/);
  assert.match(menu, /aria-controls="chat-history-rail"/);
  assert.match(menu, /<aside[^>]*id="chat-history-rail"[^>]*className="session-rail"/s);
  assert.match(menu, /className="session-rail-scrim"/);
  assert.match(menu, /aria-label=\{t\('history\.closeHistory'\)\}/);
  assert.doesNotMatch(menu, /session-popover|env-chip|▲|▾/);
  assert.match(rootCss, /@import '.\/styles\/session-rail\.css'/);
  assert.match(css, /\.session-rail\s*\{[^}]*position:\s*absolute[^}]*right:\s*0[^}]*bottom:\s*0/s);
  assert.match(css, /@media \(max-width:\s*760px\)[\s\S]*?\.session-rail-toggle\s*\{[^}]*min-height:\s*44px/s);
});

test('Given the empty workbench, when Chat starts, then it prioritizes the task and folds advanced shortcuts', async () => {
  const [empty, css] = await Promise.all([
    read('../src/EmptyState.tsx'),
    read('../src/styles/chat-messages.css'),
  ]);

  assert.match(empty, /<h2>\{t\('empty\.title'\)\}<\/h2>/);
  for (const label of ['사례 검사하기', '짧게 시험 실행', '중단 원인 찾기', '새 사례 만들기', '두 실행 비교하기', '키워드 뜻 묻기']) {
    assert.match(empty, new RegExp(`label: '${label}'`), `starter label is plain Korean: ${label}`);
  }
  assert.doesNotMatch(empty, /label: 'Validate a case'|label: 'Run a smoke test'|prompt: 'Validate /);
  assert.doesNotMatch(empty, /className="empty-context"/);
  assert.match(empty, /<details className="advanced-starters"/);
  assert.match(empty, /className="starter-group-index"/);
  assert.match(empty, /className="starter-group-note"/);
  assert.doesNotMatch(empty, /READINESS|empty-readiness/, 'the duplicate readiness strip is removed');
  assert.match(css, /\.empty-hero\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s*;/s);
  assert.match(css, /\.starter-group\s*\{[^}]*background:\s*var\(--raised\)/s, 'the starter group is a flat raised surface');
  assert.doesNotMatch(css, /\.starter-group\s*\{[^}]*gradient/s);
});
