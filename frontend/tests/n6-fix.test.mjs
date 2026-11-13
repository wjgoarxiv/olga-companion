import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import test from 'node:test';

// N6-FIX: defects found on the installed app (N6.md). Static checks on the
// tokens and rules that carry each fix; the live geometry lives in
// tests/ux/pane-squeeze.mjs.
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

async function themes() {
  const css = await read('../src/styles/base.css');
  return { css, light: hexes(block(css, ':root {')), dark: hexes(block(css, ':root[data-theme="dark"]')) };
}
const SURFACES = ['bg', 'bg-deep', 'panel', 'panel-2', 'raised'];

async function allCss() {
  const dir = new URL('../src/styles/', import.meta.url);
  const names = (await readdir(dir)).filter((n) => n.endsWith('.css'));
  return (await Promise.all(names.map((n) => readFile(new URL(n, dir), 'utf8')))).join('\n');
}
// Every rule as { selectors, body }, comments stripped, @media bodies flattened.
function rules(css) {
  const flat = css.replace(/\/\*[\s\S]*?\*\//g, '');
  return [...flat.matchAll(/([^{}@]+)\{([^{}]*)\}/g)].map((m) => ({ selectors: m[1].trim(), body: m[2] }));
}

// 1. A select-filled control carries an ink ring inside its fill, so the ring never lands select-on-select.
const LIME_FOCUSABLES = [
  '.step-cell.is-highlighted .step-open',
  '.wb-activity .ui-iconbutton[aria-pressed="true"]',
  '.wb-explorer-item[aria-current="true"]',
  '.ws-file.active',
  '.rv-var.active',
  '.ui-button-primary',
  '.wb-btn-primary',
  '.settings-sections button[aria-current="page"]',
  '.session-item.current',
  '.session-rail-toggle[aria-expanded="true"]',
  '.calibration-segment button[aria-pressed="true"]',
  '.rv-chip button[aria-pressed="true"]',
  '.sweep-value-mode button[aria-pressed="true"]',
  '.sweep-value-add button',
  '.flowpath-toolbar button.active',
  '.topo-toolbar button[aria-pressed="true"]',
  '.update-actions .update-go',
];

test('focus: select fills get an ink ring inside the fill that holds 3:1 on the select fill, both themes', async () => {
  const t = await themes();
  for (const [label, v] of [['light', t.light], ['dark', t.dark]]) {
    assert.ok(ratio(v['on-select'], v.select) >= 3, `${label} ring on the select fill`);
    for (const s of SURFACES) assert.ok(ratio(v.focus, v[s]) >= 3, `${label} outer ring on ${s}`);
  }
  const rings = rules(await allCss()).filter((r) => /:focus-visible/.test(r.selectors) && /box-shadow\s*:\s*inset[^;]*var\(--on-select\)/.test(r.body));
  assert.ok(rings.length > 0, 'a focus-visible rule paints the ink ring');
  const covered = rings.map((r) => r.selectors).join(',');
  for (const selector of LIME_FOCUSABLES) {
    assert.ok(covered.includes(`${selector}:focus-visible`), `${selector}:focus-visible has the ink ring`);
  }
  for (const r of rings) assert.doesNotMatch(r.body, /outline\s*:\s*none/, 'the ring replaces nothing with outline: none');
  // The ring sits one select band in from the edge: at the edge itself, ink would merge with a dark bar.
  for (const r of rings) assert.match(r.body, /inset 0 0 0 \d+px var\(--select\),\s*inset 0 0 0 \d+px var\(--on-select\)/, 'select band outside, ink ring inside');
});

// 2. Placeholders.
test('placeholders: one token, >= 4.5:1 on every surface and field fill, both themes', async () => {
  const t = await themes();
  const rule = rules(t.css).find((r) => /(^|,)\s*::placeholder\s*(,|$)/.test(r.selectors));
  assert.ok(rule, 'base.css sets ::placeholder for every field');
  assert.match(rule.body, /color\s*:\s*var\(--mute\)/, 'placeholder text uses --mute');
  assert.match(rule.body, /opacity\s*:\s*1/, 'placeholder opacity is reset to 1');
  for (const [label, v] of [['light', t.light], ['dark', t.dark]]) {
    for (const s of SURFACES) assert.ok(ratio(v.mute, v[s]) >= 4.5, `${label} placeholder on ${s}`);
  }
  const chat = await read('../src/styles/chat-tools.css');
  assert.doesNotMatch(chat, /::placeholder\s*\{[^}]*opacity\s*:\s*0?\.\d/, 'no fading placeholder override');
});

// 3. Composer.
test('composer: the textarea has a 3:1 edge at rest, both themes', async () => {
  const t = await themes();
  const chat = await read('../src/styles/chat-tools.css');
  const rule = rules(chat).find((r) => r.selectors === '.composer textarea');
  assert.ok(rule, '.composer textarea rule');
  assert.match(rule.body, /border\s*:\s*[\d.]+px\s+solid\s+var\(--hairline\)/, 'rest border is the --hairline edge, not transparent');
  for (const [label, v] of [['light', t.light], ['dark', t.dark]]) {
    for (const s of SURFACES) assert.ok(ratio(v.hairline, v[s]) >= 3, `${label} hairline on ${s}`);
  }
});

// 4. Settings section cards.
test('settings: the section buttons carry the 3:1 --hairline border at rest', async () => {
  const css = await read('../src/styles/settings.css');
  const rule = rules(css).find((r) => r.selectors === '.settings-sections button');
  assert.ok(rule, '.settings-sections button rule');
  assert.match(rule.body, /border\s*:\s*1px\s+solid\s+var\(--hairline\)\s*;/, 'rest border is --hairline');
  assert.doesNotMatch(rule.body, /hairline-soft/, 'no quiet border on a control');
});

// 5. Chart axis.
test('axis ticks: labels stay distinct however narrow the range, and no tick sits outside the plot', async () => {
  const sf = await import('../src/significantFigures.mjs');
  const geo = await import('../src/trendGeometry.mjs');
  assert.equal(typeof sf.formatDistinctTicks, 'function', 'formatDistinctTicks exists');
  assert.equal(typeof geo.ticksWithin, 'function', 'ticksWithin exists');
  // The installed-app case: three ticks 20 Pa apart at 3 significant figures.
  const narrow = [101260, 101280, 101300, 101320];
  const labels = sf.formatDistinctTicks(narrow, 3);
  assert.equal(new Set(labels).size, narrow.length, `distinct labels (${labels.join(' | ')})`);
  assert.deepEqual(labels, ['101,260', '101,280', '101,300', '101,320']);
  // A wide range keeps the chosen precision unchanged.
  assert.deepEqual(sf.formatDistinctTicks([0, 20, 40, 60], 3), ['0', '20', '40', '60']);
  assert.deepEqual(sf.formatDistinctTicks([0, 0.25, 0.5], 3), ['0', '0.25', '0.5']);
  // Exponent form stays distinct too.
  const tiny = sf.formatDistinctTicks([1.0001e-5, 1.0002e-5, 1.0003e-5], 3);
  assert.equal(new Set(tiny).size, 3, `exponent labels (${tiny.join(' | ')})`);
  // Ticks come back inside the data range (the plot), at least two of them.
  const inside = geo.ticksWithin(geo.niceTicks(101265, 101315, 4), 101265, 101315);
  assert.ok(inside.length >= 2, 'at least two ticks');
  assert.ok(inside.every((v) => v >= 101265 && v <= 101315), `inside the range (${inside.join(', ')})`);
  assert.deepEqual(geo.ticksWithin([0, 20, 40], 3, 3.5), [3, 3.5], 'falls back to the two ends when no nice tick fits');
  const profile = await read('../src/ProfileChart.tsx');
  const trend = await read('../src/TrendChart.tsx');
  for (const [name, source] of [['ProfileChart', profile], ['TrendChart', trend]]) {
    assert.match(source, /formatDistinctTicks/, `${name} labels its y ticks with formatDistinctTicks`);
    assert.match(source, /ticksWithin/, `${name} keeps ticks inside the plot`);
    assert.match(source, /niceTicks/, `${name} still builds nice ticks`);
  }
});

// 6. Caption: the canvas gives up height instead of pushing the caption below the fold.
test('topology caption: the canvas may shrink so the caption stays in the pane', async () => {
  const css = await read('../src/styles/workspace.css');
  const rule = rules(css).find((r) => r.selectors === '.ws-canvas .topo-canvas');
  assert.ok(rule, '.ws-canvas .topo-canvas rule');
  const min = Number(/min-height\s*:\s*(\d+)px/.exec(rule.body)?.[1]);
  assert.ok(min <= 200, `canvas min-height is a floor, not a size (got ${min}px)`);
  assert.match(css, /\.ws-canvas \.topo-meta\s*\{[^}]*flex\s*:\s*none/, 'the caption never shrinks away');
});
