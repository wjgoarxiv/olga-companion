import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

// v0.14 lane B: readable done stages (M-12), a visible primary press (M-13),
// and action links that read as links without relying on colour (H-13).
const read = async (path) => (await readFile(new URL(path, import.meta.url), 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '');
const rule = (css, selector) => {
  const start = css.indexOf(`${selector} {`);
  assert.ok(start >= 0, `${selector} rule exists`);
  return css.slice(css.indexOf('{', start) + 1, css.indexOf('}', start));
};

test('shutdown done stages keep full contrast (no opacity on --mute)', async () => {
  const css = await read('../src/styles/boot.css');
  assert.doesNotMatch(css, /\.shutdown-stages[^{]*\.is-done[^{]*\{[^}]*opacity/, 'a done stage is not faded below 4.5:1');
});

test('primary, run-go and approve have a pressed state distinct from hover', async () => {
  const css = await read('../src/styles/controls.css');
  const press = css.match(/[^{}]*\.ui-button-primary:active[^{]*\{[^}]*\}/);
  assert.ok(press, 'a primary :active rule exists');
  for (const selector of ['.ui-button-primary:active', '.run-go:active', '.approve:active']) {
    assert.ok(press[0].includes(selector), `${selector} shares the press rule`);
  }
  const hover = css.match(/\.ui-button-primary:hover[^{]*\{([^}]*)\}/)[1];
  const body = press[0].slice(press[0].indexOf('{') + 1, press[0].indexOf('}'));
  assert.notEqual(body.replace(/\s+/g, ' ').trim(), hover.replace(/\s+/g, ' ').trim(), ':active differs from :hover');
  assert.match(body, /background:\s*var\(--ink-2\)/, 'the press fill is a darker token');
  assert.doesNotMatch(body, /shadow|blur|radius|gradient/, 'flat law: no shadow, glow or radius');
});

test('receipt and download action links are underlined', async () => {
  for (const [path, selector] of [['../src/styles/controls.css', '.receipt-actions a'], ['../src/styles/results.css', '.result-downloads a']]) {
    const body = rule(await read(path), selector);
    assert.match(body, /text-decoration:\s*underline/, `${selector} is underlined`);
    assert.doesNotMatch(body, /text-decoration:\s*none/, `${selector} no longer removes the underline`);
  }
});
