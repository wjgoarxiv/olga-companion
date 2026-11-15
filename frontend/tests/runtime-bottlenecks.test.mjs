import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readRunSource } from './run-source.mjs';
import { readResultsSource } from './results-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('navigation closes diagnostics instead of leaving an interaction-blocking overlay', async () => {
  const [app, status] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/StatusBar.tsx'),
  ]);
  assert.match(app, /<StatusBar[\s\S]*?view=\{view\}/, 'the status item tracks the active view');
  assert.match(status, /useEffect\(\(\) => \{[\s\S]*?setOpen\(false\);[\s\S]*?\}, \[view\]\)/, 'the popover closes on view change');
});

test('run distinguishes active-case hydration from a genuinely empty workspace', async () => {
  const run = await readRunSource();
  assert.match(run, /activeLoaded/, 'Run must track whether active-case hydration completed');
  assert.match(run, /Loading active case/, 'Run must expose an honest loading state');
  assert.match(run, /activeLoaded\s*&&\s*!contextUnavailable\s*&&\s*!active\?\.path/, 'the empty state must wait for successful hydration');
});

test('results expose provenance so duplicate filenames are distinguishable', async () => {
  const results = await readResultsSource(import.meta.url);
  assert.match(results, /rv-file-context/);
  assert.match(results, /receiptBacked\(f\)/);
  assert.match(results, /f\.run_id/);
  assert.match(results, /modifiedLabel\(f\.modified_ns, locale\)/);
  assert.match(results, /historicalResultLabel/);
});

test('sidecar launcher uses the locked project environment and result extras', async () => {
  const pkg = JSON.parse(await read('../../package.json'));
  assert.match(pkg.scripts['dev:sidecar'], /uv run --extra results python -m olga_companion\.sidecar/);
  assert.doesNotMatch(pkg.scripts['dev:sidecar'], /^\w+=/, 'cmd.exe cannot run POSIX environment prefixes; uv installs the project package');
});
