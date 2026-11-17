import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('timeline children never shrink inside the flex scroll container', async () => {
  const css = await read('../src/styles/chat-messages.css');
  assert.match(
    css,
    /\.timeline\s*>\s*\*\s*\{[^}]*flex-shrink:\s*0/s,
    'every timeline item keeps its own height; collapse stays inside tool details',
  );
});

test('long file stems keep their distinguishing tail visible', async () => {
  const { displayStem } = await import('../src/fileNameDisplay.ts');
  assert.equal(displayStem('short.genkey'.slice(0, 5)), 'short');
  const shown = displayStem('demo_bilge_partialwet_vent_endtime60');
  assert.ok(shown.startsWith('demo_bi'), 'the head stays for orientation');
  assert.ok(shown.endsWith('endtime60'), 'the distinguishing tail stays visible');
  assert.ok(shown.length < 'demo_bilge_partialwet_vent_endtime60'.length, 'long stems still shorten');
});

test('explorer and results rails show full names with the full name exposed', async () => {
  const [explorer, rail, css] = await Promise.all([
    read('../src/shell/ExplorerPanel.tsx'),
    read('../src/ResultsInventoryRail.tsx'),
    read('../src/styles/workspace.css'),
  ]);
  for (const source of [explorer, rail]) {
    assert.doesNotMatch(source, /displayStem/, 'no mid-name ellipsis hides the distinguishing part');
    assert.match(source, /title=\{[^}]*\.name/, 'the full name stays on title');
    assert.match(source, /aria-label=\{[^}]*\.name/, 'the full name stays on aria-label');
  }
  assert.match(explorer, /className="wb-explorer-name"/, 'the tree renders the full stem');
  assert.match(rail, /className="case-name-stem"/, 'the full stem renders');
  assert.match(css, /-webkit-line-clamp:\s*2/, 'long names wrap to at most two lines');
});

test('initial topology view fits placed content with padding', async () => {
  const { fitContentView } = await import('../src/topologyFit.ts');
  const view = fitContentView(
    [{ x: 200, y: 300 }, { x: 600, y: 340 }],
    { nodeW: 150, nodeH: 40, pad: 30 },
  );
  assert.ok(view.w < 800 && view.h < 400, 'the view hugs content instead of a loose graph box');
  assert.ok(view.x <= 200 - 30 && view.y <= 300 - 30, 'padding surrounds the content');
  const map = await read('../src/TopologyMap.tsx');
  assert.match(map, /fitContentView/, 'the map opens on the fitted view without touching pan/zoom');
});

test('findings thresholds carry no example numbers', async () => {
  const [panel, fields] = await Promise.all([
    read('../src/FindingsPanel.tsx'),
    read('../src/FindingsCriterionFields.tsx'),
  ]);
  const sources = panel + fields;
  assert.doesNotMatch(sources, /placeholder="예: 200000"/, 'no numeric example in the threshold field');
  assert.doesNotMatch(sources, /placeholder="예: Pa"/, 'no unit example that reads as a recommendation');
  assert.doesNotMatch(fields, /placeholder=\{t\('findings\.unitPlaceholder'\)\}/, 'unit is a bound catalog select, not free text');
  // The threshold number stays a neutral input; the unit comes from a select
  // bound to the variable, and threshold labels show their unit.
  assert.match(fields, /placeholder=\{t\('findings\.numberPlaceholder'\)\}/);
  assert.match(fields, /unitChoicesForDimension/, 'unit options come from the dimension catalog');
  assert.match(fields, /<select[^>]*value=\{values\.unit\}/s, 'unit is chosen from a select');
  assert.match(fields, /\(.*unit.*\)|unit.*suffix/i, 'threshold labels show their unit');
});
