import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function tokenNames(css) {
  return new Set([...css.matchAll(/--([\w-]+)\s*:/g)].map((match) => match[1]));
}

function blockFor(css, selector) {
  const start = css.indexOf(selector);
  assert.ok(start >= 0, `${selector} block exists`);
  const mediaEnd = css.indexOf('}', css.indexOf('{', start));
  return css.slice(start, mediaEnd);
}

test('type scale tokens exist with the 12 to 20 scale (one step below the old 12 to 24)', async () => {
  const base = await read('../src/styles/base.css');
  for (const [name, px] of [['--fs-xs', 12], ['--fs-s', 12],
    ['--fs-m', 13], ['--fs-l', 14], ['--fs-xl', 17], ['--fs-2xl', 20]]) {
    assert.match(base, new RegExp(`${name}:\\s*calc\\(${px}px \\* var\\(--ui-scale\\)\\)`), `${name} is ${px}px at 100 %`);
  }
  assert.doesNotMatch(base, /--fs-2xs/, 'the 11 px step is removed: no visible text sets below 12 px');
});

test('new CSS carries no raw px font sizes', async () => {
  for (const file of ['../src/styles/base.css', '../src/styles/primitives.css']) {
    const css = await read(file);
    const raws = [...css.matchAll(/font-size:\s*(\d+(?:\.\d+)?)px/g)].map((match) => match[0]);
    assert.deepEqual(raws, [], `${file} sets every font size from a token`);
  }
});

test('light and dark theme blocks define the same colour role names', async () => {
  const base = await read('../src/styles/base.css');
  const light = blockFor(base, ':root[data-theme="light"]');
  const dark = blockFor(base, ':root[data-theme="dark"]');
  const lightNames = tokenNames(light);
  const darkNames = tokenNames(dark);
  for (const role of ['bg', 'panel', 'ink', 'ink-2', 'mute', 'accent', 'accent-ink',
    'accent-soft', 'signal', 'pass', 'warn', 'fail', 'info', 'focus', 'grid',
    's1', 's2', 's3', 's4', 's5', 'node', 'node-sel']) {
    assert.ok(lightNames.has(role), `light defines --${role}`);
    assert.ok(darkNames.has(role), `dark defines --${role}`);
  }
  assert.match(base, /:root:not\(\[data-theme="light"\]\)/, 'OS dark preference applies unless light is forced');
  assert.match(base, /--plot-grid-size:\s*32px 32px, 32px 32px, 160px 160px, 160px 160px/, 'the plot grid is the kit 32 px grid with 160 px majors');
});

test('motion tokens exist and reduced motion is handled', async () => {
  const base = await read('../src/styles/base.css');
  for (const token of ['--ease-ui', '--ease-enter', '--ease-exit', '--ease-snap',
    '--d-ui', '--d-enter', '--d-exit', '--d-snap']) {
    assert.match(base, new RegExp(`${token}:`), `${token} is a token`);
  }
  assert.match(base, /@media \(prefers-reduced-motion:\s*reduce\)/, 'OS reduced-motion preference is mapped');
  assert.match(base, /html\[data-motion="subtle"\]/, 'Subtle preset exists');
  assert.match(base, /html\[data-motion="off"\][\s\S]*?transition:\s*none\s*!important/, 'Off cancels everything');
});

test('density defaults to compact 32px targets and comfortable keeps 44px', async () => {
  const base = await read('../src/styles/base.css');
  assert.match(base, /--tgt:\s*calc\(32px \* var\(--ui-scale\)\)/, 'the default target token is 32px');
  assert.match(base, /\[data-density="comfortable"\][\s\S]*?--tgt:\s*calc\(44px \* var\(--ui-scale\)\)/, 'comfortable keeps the 44px target');
  const [primitives, appearance, settings] = await Promise.all([
    read('../src/styles/primitives.css'),
    read('../src/appearance.ts'),
    read('../src/SettingsView.tsx'),
  ]);
  assert.match(primitives, /min-height:\s*var\(--tgt\)/, 'key controls size from the density target token');
  assert.match(appearance, /\?\?\s*'compact'/, 'density defaults to compact');
  assert.match(appearance, /setAttribute\('data-density', choice\)/, 'the chosen density is always stamped on the root');
  assert.match(settings, /appearance\.density/, 'the density toggle reads the stored choice');
  assert.match(settings, /appearance\.setDensity/, 'the density toggle persists its choice');
});

test('spacing scale sits on a 4px grid (compact tightens the first two)', async () => {
  const base = await read('../src/styles/base.css');
  for (const [name, px] of [['--sp-1', 2], ['--sp-2', 6], ['--sp-3', 12],
    ['--sp-4', 16], ['--sp-6', 24], ['--sp-8', 32], ['--sp-10', 40]]) {
    assert.match(base, new RegExp(`${name}:\\s*calc\\(${px}px \\* var\\(--ui-scale\\)\\)`), `${name} is ${px}px at 100 %`);
  }
  assert.match(base, /\[data-density="comfortable"\][^}]*--sp-1:\s*calc\(4px[^}]*--sp-2:\s*calc\(8px/s, 'comfortable keeps the 4/8px steps');
});

test('no side stripe wider than 1px in any shipped stylesheet', async () => {
  const root = new URL('../src/styles/', import.meta.url);
  const files = (await readdir(root)).filter((name) => name.endsWith('.css'));
  assert.ok(files.includes('primitives.css'), 'the new primitives stylesheet is covered');
  for (const file of files) {
    const css = await readFile(new URL(file, root), 'utf8');
    // Structural 2 px compartment rules between the shell regions (rail,
    // Explorer, dock) are the only vertical rules allowed past 1 px; they
    // divide panes and carry no status or decorative colour.
    const withoutCompartments = css.replace(/\.(wb-activity|wb-explorer|wb-dock)\s*\{[^}]*\}/g, (rule) => rule.replace(/border-(left|right):\s*2px solid var\(--edge\);/, ''));
    assert.doesNotMatch(withoutCompartments, /border-(left|right)(?:-width)?:\s*[^;]*[2-9]\d*px/, `${file} keeps the 1px side-stripe law`);
  }
});
