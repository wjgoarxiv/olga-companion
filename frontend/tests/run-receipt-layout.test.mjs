import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

/* The preview receipt once squeezed its fact cards to ~30 px columns at 1280
   (heading stuck in a side column). These tests pin the readable floor. */

test('receipt fact grids keep a readable column minimum', async () => {
  const css = await read('../src/styles/run.css');

  for (const selector of ['\\.run-receipt', '\\.run-preview-facts']) {
    const rule = css.match(new RegExp(`${selector}\\s*\\{[^}]*\\}`, 's'));
    assert.ok(rule, `${selector} rule exists`);
    assert.doesNotMatch(rule[0], /repeat\(\d+/, `${selector} never uses a fixed column count`);
    const min = rule[0].match(/minmax\((\d+)px/);
    assert.ok(min, `${selector} sets a minmax floor`);
    assert.ok(Number(min[1]) >= 220, `${selector} floor is at least 220 px`);
  }
});

test('the preview receipt stacks heading above facts', async () => {
  const css = await read('../src/styles/run.css');

  assert.match(
    css,
    /\.receipt\.run-preview-card\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s,
    'the preview receipt is a single column so the heading sits above',
  );
});

test('long receipt values expose their full text in a tooltip', async () => {
  const [single, failure] = await Promise.all([
    read('../src/RunSingleCasePanel.tsx'),
    read('../src/RunFailurePanel.tsx'),
  ]);

  assert.match(single, /<pre[^>]*className="run-preview"[^>]*title=\{/, 'the preview command carries its full text as a tooltip');
  for (const em of failure.matchAll(/<em>([^<]*)<\/em>/g)) {
    void em;
  }
  const bareEms = [...failure.matchAll(/<em(?![^>]*\btitle=)[^>]*>/g)];
  assert.equal(bareEms.length, 0, 'every failure-receipt value has a title tooltip');
});

/* Keyboard focus keeps its ring; mouse focus must never paint one. */

test('centre containers paint no ring for mouse focus', async () => {
  const css = await read('../src/styles/shell.css');

  assert.match(
    css,
    /\.shell-main:focus:not\(\:focus-visible\)[^{]*\{[^}]*outline:\s*none/s,
    'shell-main :focus without :focus-visible paints nothing',
  );
  assert.match(
    css,
    /\.ui-tabpanel:focus:not\(\:focus-visible\)[^{]*\{[^}]*outline:\s*none/s,
    'tabpanel :focus without :focus-visible paints nothing',
  );
  assert.doesNotMatch(css, /\.shell-main:focus\s*\{[^}]*outline:\s*\d/s, 'no bare :focus outline on shell-main');
});
