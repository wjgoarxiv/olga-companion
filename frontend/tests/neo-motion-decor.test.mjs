import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

// N5b: Full-only effects, static technical decor and pixel topology icons.
const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('label scrambling is gone: no scramble module, no ScrambleText, readouts keep their plain formatters', async () => {
  const { existsSync } = await import('node:fs');
  assert.ok(!existsSync(new URL('../src/scramble.mjs', import.meta.url)), 'the scramble module is deleted');
  assert.ok(!existsSync(new URL('../src/ui/ScrambleText.tsx', import.meta.url)), 'ScrambleText is deleted');
  const { formatCoord, formatSizeLabel } = await import('../src/readoutFormat.mjs');
  assert.equal(formatCoord(12, 345), 'X 0012 · Y 0345');
  assert.equal(formatSizeLabel('W', 320.4), 'W 320 PX');
});

test('Full-only effects: the staggered wipe lives under html[data-motion="full"]; RGB glitch and scan sweep are gone (static Terminalcore)', async () => {
  const css = await read('../src/styles/motion.css');
  assert.doesNotMatch(css, /neo-glitch|neo-scan|text-shadow|run-progress-anchor\[data-inflight\]::after/, 'no RGB-offset glitch, no scan sweep');
  for (const frames of ['neo-wipe']) {
    assert.match(css, new RegExp(`@keyframes ${frames}\\b`), `${frames} keyframes exist`);
    const users = [...css.matchAll(/([^{}@]+)\{[^{}]*animation[^{}]*\b(neo-wipe)\b[^{}]*\}/g)].filter((m) => m[2] === frames);
    assert.ok(users.length > 0, `${frames} is used by a rule`);
    for (const rule of users) {
      assert.match(rule[1].trim(), /^html\[data-motion="full"\]/, `${frames} only runs in Full: ${rule[1].trim()}`);
    }
  }
  assert.match(css, /\.ui-tabpanel > \* > \*/, 'the view content wipes in per child');
  assert.match(css, /nth-child\(\d+\)[^{]*\{[^}]*animation-delay/, 'the wipe is staggered');
});

test('motion rules never touch approval controls', async () => {
  const [css, run] = await Promise.all([read('../src/styles/motion.css'), read('../src/RunSingleCasePanel.tsx')]);
  assert.doesNotMatch(css, /\.(approval|run-go|run-actions)[^{]*\{[^}]*(animation|transition)/s, 'no motion rule targets approval or the run buttons');
  const anchor = run.indexOf('run-progress-anchor');
  const goButton = run.indexOf('run-go');
  assert.ok(anchor > 0 && goButton > 0 && !run.slice(anchor, anchor + 400).includes('run-go'), 'the progress anchor does not wrap the approve button');
});

test('the step label is plain text, never decoded', async () => {
  const [step, scramble] = await Promise.all([
    read('../src/shell/StepBar.tsx'),
    read('../src/readoutFormat.mjs'),
  ]);
  assert.doesNotMatch(step, /Scramble/, 'the step bar does not decode labels');
  assert.match(step, /<span className="step-name">\{shortName\(step\.id\)\}<\/span>/, 'the label renders as is');
  assert.doesNotMatch(scramble, /scrambleFrame|NOISE|Math\.random/, 'no noise frames anywhere');
});

test('sash live size label: information in Subtle and Full, gone in Off, never announced', async () => {
  const [width, height, css] = await Promise.all([
    read('../src/PanelResizeHandle.tsx'),
    read('../src/shell/HeightResizer.tsx'),
    read('../src/styles/resizable-panels.css'),
  ]);
  assert.match(width, /className="panel-resizer-label" aria-hidden="true"/, 'width handle label is aria-hidden');
  assert.match(height, /className="panel-resizer-label" aria-hidden="true"/, 'height handle label is aria-hidden');
  assert.match(width, /formatSizeLabel\('W', width\)/, 'width label text');
  assert.match(height, /formatSizeLabel\('H', height\)/, 'height label text');
  assert.match(css, /\.panel-resizer-label\s*\{[^}]*font-family:\s*var\(--font-mono\)/s, 'mono label');
  assert.match(css, /\.panel-resizer:(hover|focus-visible|active) \.panel-resizer-label/, 'shown on hover, focus and drag');
  assert.match(css, /html\[data-motion="off"\] \.panel-resizer-label\s*\{[^}]*display:\s*none/s, 'hidden in Off');
  assert.doesNotMatch(css, /html\[data-motion="(subtle|full)"\] \.panel-resizer-label\s*\{[^}]*display:\s*none/s, 'visible in Subtle and Full');
});

test('technical decor is static and aria-hidden: frame rulers, + marks, coordinates, barcode', async () => {
  const [decor, topo, plot, title, css] = await Promise.all([
    read('../src/ui/FrameDecor.tsx'),
    read('../src/TopologyMap.tsx'),
    read('../src/ResultPlotTab.tsx'),
    read('../src/shell/TitleBar.tsx'),
    read('../src/styles/motion.css'),
  ]);
  const tags = [...decor.matchAll(/<(i|span)\b[^>]*>/g)].map((m) => m[0]);
  assert.ok(tags.length >= 3, 'FrameDecor draws rulers and marks');
  for (const tag of tags) assert.match(tag, /aria-hidden="true"/, `decor element is hidden from assistive tech: ${tag}`);
  assert.match(topo, /<FrameDecor/, 'the topology frame carries the decor');
  assert.match(plot, /<FrameDecor/, 'the chart frame carries the decor');
  assert.match(topo, /className="topo-coord" aria-hidden="true"/, 'live X/Y readout is aria-hidden');
  assert.match(topo, /onPointerMove|onMouseMove/, 'the readout follows the pointer');
  assert.match(title, /className="wb-barcode" aria-hidden="true"/, 'barcode strip is aria-hidden');
  assert.match(css, /\.frame-ruler-x[^{]*\{[^}]*border-top:\s*1px solid/s, 'the ruler is a still 1 px rule, not a gradient');
  assert.match(css, /\.frame-mark::before[^{]*\{[^}]*height:\s*1px/s, 'the + mark is two 1 px bars');
  assert.match(css, /\.topo-coord\s*\{[^}]*font-family:\s*var\(--font-mono\)/s, 'coordinates are mono');
  assert.match(css, /\.wb-barcode\s*\{[^}]*display:\s*none/s, 'the fake barcode is not painted (kit: no fake data)');
  assert.doesNotMatch(css.slice(css.indexOf('.frame-ruler-x')), /^[^}]*\{[^}]*animation/, 'the decor itself does not animate');
});

test('topology nodes use pixel symbols only: no 3D render, no image, no lucide', async () => {
  const [topo, edges, pixel] = await Promise.all([
    read('../src/TopologyMap.tsx'),
    read('../src/TopologyEdges.tsx'),
    read('../src/ui/PixelIcon.tsx'),
  ]);
  for (const [name, source] of [['TopologyMap', topo], ['TopologyEdges', edges]]) {
    assert.doesNotMatch(source, /Icon3D|lucide-react|<image\b|\/icons\//, `${name} has no 3D or lucide icon`);
  }
  assert.match(topo, /PixelIconInSvg/, 'nodes draw pixel symbols inside the SVG');
  for (const name of ['node', 'pipe', 'source', 'sink', 'valve', 'riser', 'separator']) {
    assert.match(pixel, new RegExp(`\\b${name}:\\s*\\[`), `pixel symbol ${name} is drawn`);
  }
  assert.match(topo, /SEPARATOR/, 'a separator kind maps to its symbol');
});
