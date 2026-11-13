import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('Given the product header, when it renders, then the brand carries no unexplained index', async () => {
  const [bar, css] = await Promise.all([
    read('../src/shell/TitleBar.tsx'),
    read('../src/styles/statusbar.css'),
  ]);

  assert.match(bar, /className="wordmark-primary" aria-hidden="true">OLGA<\/span>/);
  assert.doesNotMatch(bar, /wordmark-index|>01</, 'the decorative instrument index has no product meaning');
  assert.doesNotMatch(css, /\.wordmark-index\b/);
});

test('Given runtime model state, when the header renders, then provider identity never impersonates a model name', async () => {
  const [app, status] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/StatusBar.tsx'),
  ]);

  assert.match(app, /!statusDisconnected && activeModel \? operatorModelLabel\(activeModel\) : t\('status\.disconnected'\)/);
  assert.doesNotMatch(app, /model\s*\|\|\s*provider/, 'a provider name is not an exact LLM model name');
  assert.match(status, /className="wb-status-model-name"/, 'the model identity keeps its exact readout in the status bar');
  assert.match(app, /statusModelEffort \? `\$\{statusModelLabel\} · \$\{statusModelEffort\}` : statusModelLabel/, 'effort rides the exact model label');
});

test('Given compact chrome, when system status opens, then exact model identity remains available', async () => {
  const [app, status] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/StatusBar.tsx'),
  ]);

  assert.match(app, /modelLabel=\{runtimeModelLabel\}/, 'compact diagnostics receive the same exact model identity');
  assert.match(status, /\{t\('status\.aiModel'\)\}<\/span>[\s\S]*?<strong>\{modelLabel\}<\/strong>/, 'the status popover keeps model identity visible when compact chrome hides it');
});

test('Given compact chrome, when system status is closed, then its accessible name exposes runtime and exact model identity', async () => {
  const drawer = await read('../src/EnvDrawer.tsx');

  assert.match(
    drawer,
    /aria-label=\{open \? t\('env\.ariaClose', \{ runtime: resolvedRuntimeLabel, model: modelLabel \}\) : t\('env\.ariaOpen', \{ runtime: resolvedRuntimeLabel, model: modelLabel \}\)\}/,
    'the compact trigger must not hide the current runtime or model from assistive technology',
  );
});

test('Given the empty workbench, when context is shown, then it stays in the shared case selector without a duplicate card', async () => {
  const [empty, bar, title] = await Promise.all([
    read('../src/EmptyState.tsx'),
    read('../src/WorkspaceBar.tsx'),
    read('../src/shell/TitleBar.tsx'),
  ]);

  assert.doesNotMatch(empty, /empty-context/);
  assert.match(bar, /className="case-context"/);
  assert.match(title, /<WorkspaceBar[\s\S]*?activeName=\{activeCaseName\}/, 'the title-bar breadcrumb is the single case selector');
});
