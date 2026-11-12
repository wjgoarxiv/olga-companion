import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

// N6-FIX2: selected states hold a 3:1 edge against their surroundings
// (WCAG 1.4.11). Static checks on the rules and tokens; the computed edges
// are measured live in tests/ux/pane-squeeze.mjs.
const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function lum(hex) {
  const c = hex.replace('#', '');
  const v = [0, 2, 4].map((i) => {
    const x = parseInt(c.slice(i, i + 2), 16) / 255;
    return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
}
const ratio = (a, b) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);

function block(css, selector) {
  const start = css.indexOf(selector);
  assert.ok(start >= 0, `missing ${selector}`);
  const open = css.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    if (css[i] === '}') { depth -= 1; if (depth === 0) return css.slice(open + 1, i); }
  }
  throw new Error(`unbalanced ${selector}`);
}
const hexes = (body) => Object.fromEntries([...body.matchAll(/--([\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\b/g)].map((m) => [m[1], m[2].toLowerCase()]));
function rules(css) {
  const flat = css.replace(/\/\*[\s\S]*?\*\//g, '');
  return [...flat.matchAll(/([^{}@]+)\{([^{}]*)\}/g)].map((m) => ({ selectors: m[1].trim(), body: m[2] }));
}

// The select-filled selected states from N6-FIX, minus the two primary buttons
// (they already carry the 1px --edge border). Group B owns a pressed
// --state-inset shadow that the edge has to sit in front of.
const EDGE_ONLY = [
  '.step-cell.is-highlighted .step-open',
  '.wb-activity .ui-iconbutton[aria-pressed="true"]',
  '.wb-explorer-item[aria-current="true"]',
  '.rv-chip button[aria-pressed="true"]',
  '.sweep-value-add button',
  '.topo-toolbar button[aria-pressed="true"]',
  '.update-actions .update-go',
];
const EDGE_OVER_INSET = [
  '.ws-file.active',
  '.rv-var.active',
  '.session-item.current',
  '.session-rail-toggle[aria-expanded="true"]',
  '.calibration-segment button[aria-pressed="true"]',
  '.sweep-value-mode button[aria-pressed="true"]',
  '.flowpath-toolbar button.active',
];

test('selected states: the blue fill clears 3:1 on every surface in both themes, so no extra edge is needed', async () => {
  const css = await read('../src/styles/base.css');
  const light = hexes(block(css, ':root {'));
  const dark = hexes(block(css, ':root[data-theme="dark"]'));
  for (const s of ['bg', 'bg-deep', 'panel', 'panel-2', 'raised']) assert.ok(ratio(light.select, light[s]) >= 3, `select fill on light ${s}`);
  for (const s of ['bg', 'bg-deep', 'panel', 'panel-2', 'raised']) assert.ok(ratio(dark.select, dark[s]) >= 3, `select fill on dark ${s}`);
  for (const [label, selector] of [['light :root', ':root {'], ['light [data-theme]', ':root[data-theme="light"]'], ['dark [data-theme]', ':root[data-theme="dark"]'], ['dark OS', ':root:not([data-theme="light"])']]) {
    const body = block(css, selector);
    assert.match(body, /--select-edge\s*:/, `${label} defines --select-edge`);
    assert.match(body, /--select-edge\s*:\s*inset 0 0 0 0 transparent/, `${label}: no visible edge (the blue fill is already 3:1)`);
  }
  assert.ok(dark.select && light['on-select'], 'tokens exist');
  const all = rules(css);
  const focusAt = css.indexOf('.step-cell.is-highlighted .step-open:focus-visible');
  const edgeAt = css.indexOf(':root .step-cell.is-highlighted .step-open');
  assert.ok(edgeAt >= 0 && edgeAt < focusAt, 'the edge rule comes before the focus ring rule, so the focus ring still wins');
  const only = all.find((r) => EDGE_ONLY.every((s) => r.selectors.includes(`:root ${s}`)) && !/focus-visible/.test(r.selectors));
  assert.ok(only, 'one rule lists the edge-only selectors');
  assert.match(only.body, /box-shadow\s*:\s*var\(--select-edge\)\s*;/);
  const over = all.find((r) => EDGE_OVER_INSET.every((s) => r.selectors.includes(`:root ${s}`)) && !/focus-visible/.test(r.selectors));
  assert.ok(over, 'one rule lists the selectors that own a pressed shadow');
  assert.match(over.body, /box-shadow\s*:\s*var\(--select-edge\),\s*var\(--state-inset\)\s*;/);
});

test('settings: the selected section button has an ink border', async () => {
  const rule = rules(await read('../src/styles/settings.css')).find((r) => r.selectors === '.settings-sections button[aria-current="page"]');
  assert.ok(rule);
  assert.match(rule.body, /border-color\s*:\s*var\(--on-select\)/, 'ink border on the selected section');
  assert.doesNotMatch(rule.body, /border-color\s*:\s*var\(--select\)/, 'no select-on-select border');
});

test('run mode: the selected segment keeps its accent edge in front of the pressed shadow', async () => {
  const rule = rules(await read('../src/styles/run.css')).find((r) => /\.run-mode \.ui-segmented-option\[aria-checked="true"\]/.test(r.selectors));
  assert.ok(rule);
  assert.match(rule.body, /box-shadow\s*:\s*inset 0 0 0 1px var\(--accent\),\s*var\(--state-inset\)/, 'accent edge then the pressed shadow');
  const prim = rules(await read('../src/styles/primitives.css')).find((r) => r.selectors === '.ui-segmented-option[aria-checked="true"]');
  assert.match(prim.body, /box-shadow\s*:\s*inset 0 0 0 1px var\(--accent\)/, 'the base segment already has the accent edge');
});

test('panel tabs: the selected underline uses --select-line (the select blue in both themes)', async () => {
  const css = await read('../src/styles/base.css');
  for (const [label, selector, want] of [['light', ':root {', /--select-line\s*:\s*var\(--select\)/], ['light attr', ':root[data-theme="light"]', /--select-line\s*:\s*var\(--select\)/], ['dark', ':root[data-theme="dark"]', /--select-line\s*:\s*var\(--select\)/], ['dark OS', ':root:not([data-theme="light"])', /--select-line\s*:\s*var\(--select\)/]]) {
    assert.match(block(css, selector), want, `${label} --select-line`);
  }
  const rule = rules(await read('../src/styles/workbench.css')).find((r) => r.selectors === '.wb-panel-bar .ui-tab[aria-selected="true"]');
  assert.match(rule.body, /border-bottom-color\s*:\s*var\(--select-line\)/);
});
