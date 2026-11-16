import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('QLT carries a Korean label like its sibling variables', async () => {
  const { plainVariableName } = await import('../src/resultPresentation.ts');
  assert.equal(plainVariableName('QLT'), '총 액체 체적 유량');
  assert.equal(plainVariableName('GT'), '총 질량 유량');
});

test('results layout keeps the plotted chart above the fold', async () => {
  const css = await read('../src/styles/results.css');
  assert.match(css, /\.rv-main\s*\{[^}]*overflow-y:\s*auto/s, 'the main column scrolls instead of crushing the chart');
  assert.match(css, /\.rv-body\s*\{[^}]*flex:\s*none/s, 'the variables-plus-chart row never shrinks');
  const chart = css.match(/\.rv-chart\s*\{[^}]*min-height:\s*(\d+)px/s);
  assert.ok(chart, 'the chart box has a minimum height');
  assert.ok(Number(chart[1]) >= 280, `chart keeps a usable height, got ${chart[1]}px`);
  assert.match(css, /\.rv-vars\s*\{[^}]*max-height:\s*\d+px/s, 'the variable list stays usable with its own scroll');
});
