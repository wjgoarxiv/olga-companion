import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

async function readCss() {
  const root = await read('../src/styles.css');
  const imports = [...root.matchAll(/@import ['"](.+)['"];/g)];
  const imported = await Promise.all(imports.map((match) => read(`../src/${match[1]}`)));
  return [root, ...imported].join('\n');
}

test('offline runtime keeps every primary destination visible without mounting protected views', async () => {
  const [app, centre] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/CentreViews.tsx'),
  ]);

  assert.match(app, /import \{ RuntimeUnavailableView \} from '\.\/RuntimeUnavailableView'/);
  assert.match(
    app,
    /runtime\.state !== 'online'[^]*?<RuntimeUnavailableView[^]*?view=\{view\}[^]*?onRetry=\{runtime\.retry\}/s,
    'an offline workflow selection renders a scoped recovery surface',
  );
  for (const view of ['WorkspaceView', 'ResultsView', 'RunView', 'SettingsView']) {
    assert.match(
      centre,
      new RegExp(`<${view}[^>]*key=\\{contextKey\\}`),
      `${view} mounts only inside the online-gated centre, never before hydration is safe`,
    );
  }
  assert.doesNotMatch(app, /gated:\s*!activeCaseName/, 'a missing case is context, not a disabled-looking navigation gate');
});

test('shared offline surface explains the boundary and reuses the sidecar retry action', async () => {
  const [view, css] = await Promise.all([
    read('../src/RuntimeUnavailableView.tsx'),
    readCss(),
  ]);

  for (const label of ['Workspace', 'Results', 'Run', 'Settings']) {
    assert.match(view, new RegExp(`title${label}`, 'i'), `${label} has destination-specific offline copy`);
  }
  assert.match(view, /<WorkbenchPrompt/);
  assert.match(view, /contextLabel=\{t\('offline\.connectionState'\)\}/);
  assert.match(view, /onClick=\{onRetry\}/);
  assert.match(view, /busy=\{busy\}/);
  assert.match(view, /t\('offline\.navAvailable'\)/);
  assert.match(view, /t\('offline\.pauseTitle'\)/);
  assert.match(css, /\.runtime-unavailable-view\s*\{[^}]*overflow-y:\s*auto/s);
  assert.match(css, /@media\s*\(max-width:\s*760px\)[^]*?\.runtime-unavailable-view\s*\{[^}]*padding:/s);
});
