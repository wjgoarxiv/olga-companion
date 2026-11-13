import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('Given an unavailable runtime, when the header renders, then label, state, and recovery align as one status unit', async () => {
  const [status, css] = await Promise.all([
    read('../src/RuntimeNavStatus.tsx'),
    read('../src/styles/runtime-status.css'),
  ]);

  assert.match(status, /className="runtime-nav-status-label">\{t\('runtime\.label'\)\}<\/span>/);
  assert.match(status, /stateKey:\s*'runtime\.offlineState'/);
  assert.match(status, /<strong>\{t\(presentation\.stateKey\)\}<\/strong>/);
  assert.match(css, /\.runtime-nav-status\s*\{[^}]*min-height:\s*42px[^}]*border-radius:\s*var\(--r-s\)/s);
  assert.match(css, /\.runtime-nav-status-copy\s*\{[^}]*align-content:\s*center[^}]*gap:\s*2px/s);
});

test('Given model metadata is unavailable, when the header renders, then the user sees an explicit AI connection state', async () => {
  const [app, status, css, ko] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/StatusBar.tsx'),
    read('../src/styles/statusbar.css'),
    read('../src/i18n/ko.ts'),
  ]);

  assert.match(app, /!statusDisconnected && activeModel \? operatorModelLabel\(activeModel\) : t\('status\.disconnected'\)/);
  assert.match(ko, /'status\.disconnected': '\uc5f0\uacb0 \uc548 \ub428'/, 'an unavailable model reads as \uc5f0\uacb0 \uc548 \ub428 in ko');
  assert.doesNotMatch(app, /: '\uc5f0\uacb0 \uc548 \ub428'|Not connected/, 'the status bar carries no hardcoded connection copy');
  assert.match(status, /className="wb-status-model-kicker">\{t\('status\.aiModel'\)\}<\/span>/);
  assert.match(css, /\.wb-status\s*\{[^}]*height:\s*var\(--sb-h\)/s, 'the single thin bar replaces the 42px model card');
});

test('Given the OLGA lockup, when it appears in the title bar, then COMPANION remains legible', async () => {
  const [bar, css] = await Promise.all([
    read('../src/shell/TitleBar.tsx'),
    read('../src/styles/workbench.css'),
  ]);

  assert.match(bar, /className="wordmark-secondary" aria-hidden="true">COMPANION<\/span>/);
  assert.match(css, /\.wordmark-secondary\s*\{[^}]*font-size:\s*var\(--fs-xs\)[^}]*letter-spacing:\s*var\(--track-label\)/s, 'the 12px floor token holds for the lockup line');
});

test('the runtime heartbeat is a shaped dot, not a text glyph', async () => {
  const [bar, css] = await Promise.all([
    read('../src/shell/StatusBar.tsx'),
    read('../src/styles/statusbar.css'),
  ]);

  assert.doesNotMatch(bar, /wb-heartbeat[^>]*>●</, 'no text glyph inside the heartbeat');
  assert.match(css, /\.wb-heartbeat\s*\{[^}]*border-radius:\s*var\(--r-s\)/s, 'the heartbeat is a drawn square block (hard-edge theme)');
});
