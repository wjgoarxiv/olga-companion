import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import test from 'node:test';

const stylesDir = new URL('../src/styles/', import.meta.url);
const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function blocks(css) {
  const source = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const found = [];
  const re = /([^{}@]+)\{([^{}]*)\}/g;
  let match;
  while ((match = re.exec(source))) found.push({ selector: match[1].trim().replace(/\s+/g, ' '), body: match[2] });
  return found;
}

function isLabel(selector, body) {
  return /text-transform:\s*uppercase/.test(body)
    || /kicker|eyebrow|wordmark-secondary/.test(selector);
}

function letterSpacingEm(body) {
  const match = body.match(/letter-spacing:\s*(-?\d*\.?\d+)em/);
  return match ? Number(match[1]) : null;
}

async function styleFiles() {
  const names = (await readdir(stylesDir)).filter((name) => name.endsWith('.css')).sort();
  const files = [];
  for (const name of names) files.push({ name, css: await readFile(new URL(name, stylesDir), 'utf8') });
  return files;
}

test('label letter-spacing stays at most 0.04em, and Hangul tracking is 0', async () => {
  const files = await styleFiles();
  const offenders = [];
  const tracked = [];
  for (const file of files) {
    if (file.name === 'chat-messages.css') continue;
    for (const block of blocks(file.css)) {
      if (!isLabel(block.selector, block.body)) continue;
      const spacing = letterSpacingEm(block.body);
      if (spacing != null && spacing > 0.04) offenders.push(`${file.name} ${spacing}em ${block.selector}`);
      if (spacing != null && spacing > 0) tracked.push(block.selector);
    }
  }
  assert.deepEqual(offenders, [], 'uppercase and label rules stay at or under 0.04em');
  const base = files.find((file) => file.name === 'base.css').css;
  const ko = base.match(/:lang\(ko\)\s+:is\(([^)]*)\)\s*\{([^}]*)\}/);
  assert.ok(ko, 'base.css sets Hangul label tracking in one :lang(ko) :is() rule');
  assert.match(ko[2], /letter-spacing:\s*0\s*;/, 'Hangul labels use 0 tracking');
  const covered = ko[1];
  for (const selector of tracked) {
    for (const part of selector.split(',')) {
      const piece = part.trim();
      assert.ok(covered.includes(piece), `:lang(ko) covers ${piece}`);
    }
  }
});

test('dense 12px rows declare line-height 1.35 and prose declares 1.5', async () => {
  const [workbench, guide, primitives, base] = await Promise.all([
    read('../src/styles/workbench.css'),
    read('../src/styles/simulation-guide.css'),
    read('../src/styles/primitives.css'),
    read('../src/styles/base.css'),
  ]);
  assert.match(workbench, /\.wb-pane-head\s*\{[^}]*line-height:\s*1\.35/s);
  assert.match(workbench, /\.wb-explorer-name\s*\{[^}]*line-height:\s*1\.35/s);
  assert.match(workbench, /\.wb-explorer-meta\s*\{[^}]*line-height:\s*1\.35/s);
  assert.match(guide, /\.step-name\s*\{[^}]*line-height:\s*1\.35/s);
  assert.match(primitives, /\.ui-tab\s*\{[^}]*line-height:\s*1\.35/s);
  assert.match(base, /body\s*\{[^}]*line-height:\s*1\.5/s);
});

test('content values use --ink and metadata keeps --mute', async () => {
  const [workbench, workspace, results] = await Promise.all([
    read('../src/styles/workbench.css'),
    read('../src/styles/workspace.css'),
    read('../src/styles/results.css'),
  ]);
  assert.match(workbench, /\.wb-explorer-name\s*\{[^}]*color:\s*var\(--ink\)/s);
  assert.match(workbench, /\.wb-explorer-item\[aria-current="true"\] \.wb-explorer-name\s*\{[^}]*color:\s*var\(--on-select\)/s);
  assert.match(workbench, /\.wb-explorer-meta\s*\{[^}]*color:\s*var\(--mute\)/s);
  assert.match(workbench, /\.wb-explorer-ext\s*\{[^}]*color:\s*var\(--mute\)/s);
  assert.match(workspace, /\.ws-file-name\s*\{[^}]*color:\s*var\(--ink\)/s);
  assert.match(workspace, /\.ws-file-kb\s*\{[^}]*color:\s*var\(--mute\)/s);
  assert.match(results, /\.rv-var-name\s*\{[^}]*color:\s*var\(--ink\)/s);
  assert.match(results, /\.rv-var-plain\s*\{[^}]*color:\s*var\(--ink\)/s);
  assert.match(results, /\.rv-var-unit\s*\{[^}]*color:\s*var\(--mute\)/s);
  assert.match(results, /\.trend-sample-count\s*\{[^}]*color:\s*var\(--ink\)/s);
});

test('neo-pulse is gone: no run-state pulse in any preset', async () => {
  const css = (await read('../src/styles/motion.css')).replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(css, /neo-pulse|neo-flick/, 'no pulsing or flickering keyframes');
  assert.doesNotMatch(css, /\.run-state[^{]*\{[^}]*animation/, 'the run state pill never animates');
});

test('the blanket reduced-motion kill lives in base.css only', async () => {
  const files = await styleFiles();
  const unqualified = files.filter((file) => /@media\s*\(\s*prefers-reduced-motion:\s*reduce\s*\)\s*\{\s*\*\s*\{[^}]*animation:\s*none/.test(file.css)).map((file) => file.name);
  assert.deepEqual(unqualified, [], 'no stylesheet kills every animation on OS reduce without the data-motion qualifier');
  const sources = files.filter((file) => /:root:not\(\[data-motion\]\)\s*\*/.test(file.css) && /animation:\s*none\s*!important/.test(file.css)).map((file) => file.name);
  assert.deepEqual(sources, ['base.css']);
});

test('the design contract tells the truth about pulse, the approval card and the xs step', async () => {
  const doc = await read('../../docs/design-contract.md');
  assert.match(doc, /--fs-xs` and `--fs-s` are the same 12 px step/);
  assert.match(doc, /:lang\(ko\)/);
  assert.match(doc, /letter-spacing 0/);
  assert.match(doc, /approval card[\s\S]{0,500}Full/);
  for (const gone of ['neo-pulse', 'ScrambleText', 'c8ff1a', 'ff3d8b']) {
    assert.ok(!doc.includes(gone), `the design contract no longer documents ${gone}`);
  }
  assert.match(doc, /Terminalcore/, 'the contract describes the Terminalcore theme');
  assert.match(doc, /MesloLGSNF-Regular\.woff2/, 'the contract names the woff2 Meslo files');
  assert.doesNotMatch(doc, /take no new motion beyond/);
});
