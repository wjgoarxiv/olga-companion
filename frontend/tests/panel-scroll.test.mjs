import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

// Owner report 2026-11-16: a .tab with many findings filled the Problems panel but it
// could not scroll. The bar grew to its content (flex item, min-height auto) and the
// centred tabpanel overflowed it, so overflow:auto never engaged.
test('the bottom panel bar is bounded and its tab panel is the one scroller', async () => {
  const css = (await readFile(new URL('../src/styles/workbench.css', import.meta.url), 'utf8')).replace(/\s+/g, ' ');
  const bar = css.match(/\.wb-panel-bar \{([^}]*)\}/)?.[1] ?? '';
  assert.match(bar, /flex: 1 1 auto/);
  assert.match(bar, /min-height: 0/);
  assert.match(bar, /grid-template-rows: auto minmax\(0, 1fr\)/);
  assert.match(bar, /background: var\(--raised\)/, 'keeps the dark-token guard');
  const panel = css.match(/\.wb-panel-bar \.ui-tabpanel \{([^}]*)\}/)?.[1] ?? '';
  assert.match(panel, /align-self: stretch/);
  assert.match(panel, /min-height: 0/);
  assert.match(panel, /overflow: auto/);
});
