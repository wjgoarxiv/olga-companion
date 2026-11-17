import assert from 'node:assert/strict';
import { readdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const STYLES = new URL('../src/styles/', import.meta.url);
const SCALES = [80, 90, 100, 110, 120, 130];

// N2 owner decision: one root variable scales type, spacing and control
// tokens (no CSS zoom: pointer maths in the sash handles must stay in CSS px).

test('appearance stores, parses and applies the UI scale', async () => {
  const appearance = await read('../src/appearance.ts');
  assert.match(appearance, /UI_SCALE_KEY\s*=\s*'olga-companion\.ui-scale\.v1'/, 'the scale has its own storage key beside theme and density');
  assert.match(appearance, /UI_SCALES[^=]*=\s*\[\s*80,\s*90,\s*100,\s*110,\s*120,\s*130\s*\]/, 'the six approved steps');
  assert.match(appearance, /export function parseUiScale/, 'stored values are validated');
  assert.match(appearance, /loadUiScale[\s\S]*?\?\?\s*100/, 'the default scale is 100 %');
  assert.match(appearance, /setAttribute\('data-ui-scale'/, 'the scale reaches the document root');
  assert.match(appearance, /initAppearance[\s\S]*?applyUiScaleAttribute\(loadUiScale\(\)\)/, 'startup restores the scale before first paint');
  assert.match(appearance, /setUiScale/, 'the hook exposes a setter that persists');
});

test('base.css drives every type, spacing and control token from --ui-scale', async () => {
  const base = await read('../src/styles/base.css');
  assert.match(base, /:root\s*\{[^}]*--ui-scale:\s*1;/s, 'the root default is 1');
  for (const step of SCALES) {
    assert.match(base, new RegExp(`\\[data-ui-scale="${step}"\\]\\s*\\{[^}]*--ui-scale:\\s*${step / 100}\\s*;`, 's'), `step ${step} sets --ui-scale: ${step / 100}`);
  }
  for (const name of ['fs-xs', 'fs-s', 'fs-m', 'fs-l', 'fs-xl', 'fs-2xl', 'sp-1', 'sp-2', 'sp-3', 'sp-4', 'sp-6', 'sp-8', 'sp-10', 'tgt', 'ctl-h']) {
    assert.match(base, new RegExp(`--${name}:\\s*calc\\([^;]*var\\(--ui-scale\\)\\)`), `--${name} scales with --ui-scale`);
  }
  assert.doesNotMatch(base, /\bzoom\s*:/, 'no CSS zoom in base.css');
});

test('no stylesheet uses CSS zoom or an unscaled px font size', async () => {
  const offenders = [];
  for (const file of readdirSync(STYLES)) {
    if (!file.endsWith('.css')) continue;
    const css = await read(`../src/styles/${file}`);
    if (/(^|[;{\s])zoom\s*:/.test(css)) offenders.push(`${file}: zoom`);
    for (const m of css.matchAll(/(^|[;{\s])font-size\s*:\s*(\d+(?:\.\d+)?)px/g)) offenders.push(`${file}: ${m[0].trim()}`);
    for (const m of css.matchAll(/(^|[;{\s])font\s*:\s*(?:[\d]{3}\s+)?(\d+(?:\.\d+)?)px/g)) offenders.push(`${file}: ${m[0].trim()}`);
  }
  assert.deepEqual(offenders, [], 'every font size flows through a scaled token or calc(... * var(--ui-scale))');
});

test('default type steps sit one step below the old 12-24 ladder and keep the 12 px floor at 100 %', async () => {
  const base = await read('../src/styles/base.css');
  const want = { 'fs-xs': 12, 'fs-s': 12, 'fs-m': 13, 'fs-l': 14, 'fs-xl': 17, 'fs-2xl': 20 };
  for (const [name, px] of Object.entries(want)) {
    assert.match(base, new RegExp(`--${name}:\\s*calc\\(${px}px \\* var\\(--ui-scale\\)\\)`), `--${name} is ${px}px at 100 %`);
  }
  assert.ok(want['fs-xs'] >= 12 && want['fs-s'] >= 12, 'the two smallest steps hold the 12 px floor');
});

// ai-dock-and-neo-fx todo 3: dock message text rides the type scale, so it follows the Settings UI scale.
function ruleBody(css, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = css.match(new RegExp(`(?:^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`, 'm'));
  return m ? m[1] : '';
}

test('dock message text declares token sizes and a 1.5 line-height', async () => {
  const messages = await read('../src/styles/chat-messages.css');
  const bubble = ruleBody(messages, '.bubble');
  assert.match(bubble, /font-size:\s*var\(--fs-m\)/, '.bubble uses --fs-m so it scales with the UI scale');
  assert.match(bubble, /line-height:\s*1\.5\b/, '.bubble keeps line-height 1.5');
  assert.match(ruleBody(messages, '.md h3'), /font-size:\s*var\(--fs-l\)/, '.md h3 is at least body size');
  assert.match(ruleBody(messages, '.md h4'), /font-size:\s*var\(--fs-(?:l|m)\)/, '.md h4 is at least body size');
  assert.match(ruleBody(messages, '.md h5, .md h6'), /font-size:\s*var\(--fs-m\)/, '.md h5 and h6 are body size');
  assert.match(ruleBody(messages, '.md code'), /font-size:\s*var\(--fs-s\)/, '.md code uses --fs-s, not a relative em');
  assert.match(ruleBody(messages, '.md p'), /line-height:\s*1\.5\b/, '.md paragraphs share the bubble line-height');
});

test('every composer textarea rule that sets a size uses --fs-m', async () => {
  const sizes = [];
  for (const file of readdirSync(STYLES)) {
    if (!file.endsWith('.css')) continue;
    const css = await read(`../src/styles/${file}`);
    for (const rule of css.matchAll(/\.composer\s+textarea\s*\{([^}]*)\}/g)) {
      for (const m of rule[1].matchAll(/(?:^|[;\s])font-size\s*:\s*([^;]+)/g)) sizes.push(`${file}: ${m[1].trim()}`);
    }
  }
  assert.ok(sizes.length > 0, 'a composer textarea size is declared');
  assert.deepEqual(sizes.filter((s) => !/var\(--fs-m\)$/.test(s)), [], 'the composer follows body size at every breakpoint');
});

test('Settings offers the scale as a keyboard-operable segmented control with both labels', async () => {
  const [view, ko, en] = await Promise.all([read('../src/SettingsView.tsx'), read('../src/i18n/ko.ts'), read('../src/i18n/en.ts')]);
  assert.match(view, /appearance\.uiScale/, 'the control reads the stored scale');
  assert.match(view, /appearance\.setUiScale/, 'the control persists its choice');
  assert.match(view, /UI_SCALES/, 'options come from the approved steps');
  assert.match(ko, /'settings\.uiScale':\s*'글자 크기 \/ 화면 배율'/, 'ko label');
  assert.match(en, /'settings\.uiScale':\s*'Text size \/ UI scale'/, 'en label');
});
