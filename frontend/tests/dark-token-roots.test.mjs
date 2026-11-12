import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

const readCss = async () => {
  const root = await read('../src/styles.css');
  const imports = [...root.matchAll(/@import ['"](.+)['"];/g)];
  const imported = await Promise.all(imports.map((match) => read(`../src/${match[1]}`)));
  return [root, ...imported].join('\n');
};

/* Dark fix-up: the shared controls and the panel tab strip are the root
 * cause of the white-card/green-text dark renders. They must read the
 * dual-theme tokens so every consumer is right in both themes. */

test('shared controls read the dual-theme tokens', async () => {
  const [controls, workbench] = await Promise.all([
    read('../src/styles/controls.css'),
    read('../src/styles/workbench.css'),
  ]);
  assert.match(controls, /\.ui-button\s*\{[^}]*background:\s*var\(--raised\)/s, 'default buttons sit on the raised token');
  assert.match(controls, /\.ui-button:hover:not\(:disabled\)\s*\{[^}]*background:\s*var\(--hairline-soft\)/s, 'button hover stays inside the hairline family');
  assert.match(controls, /\.ui-button:disabled\s*\{[^}]*background:\s*var\(--btn-disabled-bg\)[^}]*border:\s*1px solid var\(--btn-disabled-border\)/s, 'disabled buttons use the solid shared triple, never a dashed outline');
  assert.match(controls, /\.operation-status\s*\{[^}]*background:\s*var\(--raised\)/s, 'status cards sit on the raised token');
  assert.match(controls, /\.operation-status\s*\{[^}]*color:\s*var\(--ink\)/s, 'status copy follows the ink token');
  assert.match(controls, /\.receipt\s*\{[^}]*background:\s*var\(--raised\)/s, 'receipts sit on the raised token');
  assert.match(workbench, /\.wb-panel-bar\s*\{[^}]*background:\s*var\(--raised\)[^}]*border-top:\s*2px solid var\(--select\)/s, 'the panel tab strip is a raised surface with a 2px accent rule');
  assert.doesNotMatch(workbench, /\.wb-panel-bar \.ui-tablist\s*\{[^}]*background:\s*var\(--ink\)/s, 'no loud green bar in dark mode');
});

/* No light-only hard-codes anywhere in the shipped stylesheets. */

test('no light-only colour hard-codes in shipped styles', async () => {
  const css = await readCss();
  assert.doesNotMatch(css, /#fff(?:fff)?\b/i, 'no near-white hex escapes the tokens');
  assert.doesNotMatch(css, /:\s*white\s*;/i, 'no named white escapes the tokens');
  assert.doesNotMatch(css, /rgba?\(\s*255\s*,\s*255\s*,\s*255\s*(,\s*1(\.0+)?)?\s*\)/i, 'no opaque white rgb escapes the tokens');
});
