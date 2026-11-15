import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('provider selection is stored by the sidecar, not the webview', async () => {
  const api = await read('../src/providerSelectionApi.ts');
  const app = await read('../src/App.tsx');
  assert.match(api, /\/api\/llm-selection/);
  assert.match(api, /method: 'PUT'/);
  const hook = await read('../src/useProviderSelection.ts');
  assert.match(app, /useProviderSelection/);
  assert.match(hook, /loadProviderSelection/);
  assert.match(hook, /saveProviderSelection/);
  assert.doesNotMatch(app, /olga_effort/);
  assert.doesNotMatch(await read('../src/SettingsView.tsx'), /llm-selection/);
});
