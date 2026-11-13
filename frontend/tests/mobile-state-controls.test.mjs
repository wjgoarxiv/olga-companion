import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const css = (name) => readFile(new URL(`../src/styles/${name}`, import.meta.url), 'utf8');
const mobile = (source) => source.slice(source.lastIndexOf('@media (max-width: 760px)'));

test('recovery and navigation controls stay 44px on phones, and the results header cannot cover the list', async () => {
  const [status, rail, tools, results, run] = await Promise.all([
    css('runtime-status.css'), css('session-rail.css'), css('chat-tools.css'), css('results.css'), css('run.css'),
  ]);

  // The only recovery control when the runtime is offline.
  assert.match(mobile(status), /\.runtime-nav-status \.ui-button\s*\{[^}]*min-height:\s*44px/);
  assert.match(mobile(rail), /\.session-rail-close\s*\{[^}]*width:\s*44px;\s*height:\s*44px/);
  assert.match(tools, /@media \(max-width: 760px\)\s*\{\s*\.queued-message-remove\s*\{[^}]*44px/);
  assert.match(mobile(run), /\.sweep-value-mode button[^{]*\{[^}]*min-height:\s*44px/);
  // The header (title, filter, case toggle, refresh) is taller than the phone rail it sits in.
  assert.match(mobile(results), /\.rv-files-head\s*\{\s*position:\s*static/);
});
