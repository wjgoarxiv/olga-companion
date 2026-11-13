import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

// Full-only stepped wipe and pixel loader. The pane-title glitch and the strobe
// stamp were removed (Terminalcore: no flicker); these tests pin their absence.
const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const VIEWPORT_PX = 1280 * 800;
const FLASH_BOX_MAX = VIEWPORT_PX * 0.02;

function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

function keyframes(css, name) {
  const match = stripComments(css).match(new RegExp(`@keyframes\\s+${name}\\s*\\{([\\s\\S]*?)\\n\\}`));
  assert.ok(match, `${name} keyframes exist`);
  return match[1];
}

function usersOf(css, name) {
  return [...stripComments(css).matchAll(new RegExp(`([^{}@]+)\\{[^{}]*animation[^{}]*\\b${name}\\b[^{}]*\\}`, 'g'))];
}

function flashesIn(body) {
  const stops = [...body.matchAll(/([\d.]+)%\s*\{[^}]*opacity:\s*([\d.]+)/g)]
    .map((match) => ({ at: Number(match[1]), opacity: Number(match[2]) }))
    .sort((a, b) => a.at - b.at);
  let swings = 0;
  for (let index = 1; index < stops.length; index += 1) {
    const from = stops[index - 1].opacity;
    const to = stops[index].opacity;
    if ((from <= 0.2 && to >= 0.8) || (from >= 0.8 && to <= 0.2)) swings += 1;
  }
  return swings / 2;
}

test('stepped wipe and pixel loader run only in Full; the pane-title glitch is gone', async () => {
  const css = stripComments(await read('../src/styles/motion.css'));
  const controls = stripComments(await read('../src/styles/controls.css'));
  const combined = `${css}\n${controls}`;
  const wipe = usersOf(combined, 'neo-wipe');
  assert.ok(wipe.length > 0, 'neo-wipe is used');
  for (const rule of wipe) {
    assert.match(rule[1].trim(), /^html\[data-motion="full"\]/, 'dissolve stays in Full');
    const declared = rule[0];
    const steps = declared.match(/steps\(\s*(\d+)/);
    assert.ok(steps, 'dissolve is a stepped mask');
    assert.ok(Number(steps[1]) <= 6 && Number(steps[1]) >= 1, 'at most 6 steps');
    const duration = declared.match(/(\d+)ms/);
    assert.ok(duration && Number(duration[1]) <= 240, 'dissolve is at most 240 ms');
  }
  assert.doesNotMatch(combined, /pane-title-glitch|text-shadow/, 'no tab-edge flicker and no RGB-offset text shadow');
  assert.doesNotMatch(combined, /\.ui-tab\[aria-selected="true"\]::(?:before|after)/, 'the active tab carries no animated edge layers');
  const loader = keyframes(combined, 'pixel-loader');
  assert.match(loader, /transform/);
  assert.doesNotMatch(loader, /opacity/, 'the pixel loader does not strobe');
  const loaderUsers = usersOf(combined, 'pixel-loader');
  assert.ok(loaderUsers.length > 0, 'chat activity uses the pixel loader');
  for (const rule of loaderUsers) {
    assert.match(rule[1].trim(), /^html\[data-motion="full"\]/);
    assert.match(rule[0], /steps\(\s*3\s*,\s*end\s*\)/, 'the pixel loader is steps(3, end)');
  }
  const base = stripComments(await read('../src/styles/base.css'));
  assert.match(base, /html\[data-motion="off"\] \*[^{]*\{[^}]*animation:\s*none\s*!important/s, 'Off cancels the loader: a still state');
  assert.match(base, /:root:not\(\[data-motion\]\) \*[^{]*\{[^}]*animation:\s*none\s*!important/s, 'OS reduced motion cancels it too');
  const box = combined.match(/\.activity-loader-pixels\s*\{([^}]*)\}/);
  assert.ok(box, 'pixel loader has a box');
  const width = Number(box[1].match(/width:\s*(\d+)px/)?.[1]);
  const height = Number(box[1].match(/height:\s*(\d+)px/)?.[1]);
  assert.ok(width > 0 && height > 0 && width * height <= 256, 'pixel loader stays a small block');
});

test('the strobe stamp is gone: no keyframes, no box, no markup', async () => {
  const css = stripComments(`${await read('../src/styles/motion.css')}\n${await read('../src/styles/run.css')}`);
  assert.doesNotMatch(css, /strobe-stamp|\.fx-stamp/, 'no strobe keyframes or stamp rules');
  const [run, failure] = await Promise.all([read('../src/RunSingleCasePanel.tsx'), read('../src/RunFailurePanel.tsx')]);
  assert.doesNotMatch(run, /fx-stamp/);
  assert.doesNotMatch(failure, /fx-stamp/);
});

test('nothing blinks: no opacity-pulse keyframes in any stylesheet', async () => {
  const dir = new URL('../src/styles/', import.meta.url);
  const { readdirSync } = await import('node:fs');
  for (const file of readdirSync(dir).filter((name) => name.endsWith('.css'))) {
    const css = stripComments(await read(`../src/styles/${file}`));
    assert.doesNotMatch(css, /neo-pulse|neo-flick|wb-beat|@keyframes pulse\b|animation:\s*pulse\b|activity-loader-breathe|wb-poweron|wb-theme-veil/, `${file} has no blink, pulse or flash`);
  }
});

test('hover lift skips approve, primary, busy and run-go', async () => {
  const motion = stripComments(await read('../src/styles/motion.css'));
  const lift = motion.match(/\.ui-button:not\(\.approval-card \*\)[^{]*\{[^}]*translate/s);
  assert.ok(lift, 'the button hover lift still exists');
  for (const guard of [':not(.approve)', ':not(.ui-button-primary)', ':not(.run-go)', ':not([data-busy])']) {
    assert.match(lift[0], new RegExp(guard.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), guard);
  }
  const wb = motion.match(/\.wb-btn:not\(\.approval-card \*\)[^{]*\{[^}]*translate/s);
  assert.ok(wb, 'the workbench button hover lift still exists');
  assert.match(wb[0], /:not\(\.wb-btn-primary\)/);
  assert.match(wb[0], /:not\(\[data-busy\]\)/);
  assert.doesNotMatch(motion, /(^|[},])\s*\.run-go[^{]*\{[^}]*(animation|transition|translate)/, 'run-go has no lift of its own');
});
