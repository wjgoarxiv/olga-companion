import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('768px widths give results filter/refresh and topo hits 44px without layout spill', async () => {
  const [results, tools, edges, shell] = await Promise.all([
    read('../src/styles/results.css'),
    read('../src/styles/chat-responsive.css'),
    read('../src/TopologyEdges.tsx'),
    read('../src/styles/workbench.css'),
  ]);

  assert.match(
    shell,
    /\.wb-explorer-filter input\s*\{[^}]*min-height:\s*var\(--tgt\)/s,
    'the single explorer filter keeps the 44px touch target',
  );
  assert.match(
    results,
    /@media \(max-width:\s*768px\)[\s\S]*?\.rv-files-head \.ui-button\s*\{[^}]*min-height:\s*44px/s,
    'refresh meets 44px at 768px too',
  );
  assert.match(
    tools,
    /\.topo-edge \.topo-edge-hit\s*\{[^}]*stroke-width:\s*22/s,
    'edge hit stroke widens but stays under the 24-unit parallel spacing',
  );
  assert.match(edges, /height=\{20\}/, 'label hit rect fills the 20-unit collision lane');
});

test('narrow and coarse-pointer screens get a 44px touch list reusing map selection', async () => {
  const [map, css] = await Promise.all([
    read('../src/TopologyMap.tsx'),
    read('../src/styles/chat-responsive.css'),
  ]);
  assert.match(map, /topo-touch-list/, 'a compact list renders under the map');
  assert.match(map, /topo-touch-target/, 'each row is a real button');
  assert.match(map, /onClick=\{\(\) => selectFlowpath\(index, edge\.label\)\}/, 'flowpath rows reuse the shared edge select handler');
  assert.match(map, /setSelected\(\{ kind: 'node', id: n\.id \}\)/, 'node rows reuse the shared node selection');
  assert.match(map, /aria-pressed/, 'rows expose selection state');
  assert.match(
    css,
    /@media[^{]*\(max-width:\s*768px\)[^{]*\{[\s\S]*?\.topo-touch-list\s*\{[^}]*display:\s*grid/s,
    'the list appears at narrow widths',
  );
  assert.match(
    css,
    /\.topo-touch-target\s*\{[^}]*min-height:\s*44px/s,
    'every row meets the 44px touch minimum',
  );
});

test('short screens shrink headings and tall canvases instead of pushing content out', async () => {
  const [prompts, responsive] = await Promise.all([
    read('../src/styles/workbench-prompts.css'),
    read('../src/styles/chat-responsive.css'),
  ]);

  assert.match(
    prompts,
    /@media \(max-height:\s*700px\)[\s\S]*?\.workbench-prompt h2\s*\{[^}]*font-size:\s*var\(--fs-2xl\)/s,
    'empty-state titles drop below the 31px desktop clamp on short screens',
  );
  assert.match(
    prompts,
    /@media \(max-height:\s*700px\)[\s\S]*?\.workbench-prompt-context\s*\{[^}]*min-height:\s*0/s,
    'the 104px context card stops reserving height on short screens',
  );
  assert.match(
    responsive,
    /@media \(max-height:\s*700px\)[\s\S]*?\.topo-canvas\s*\{[^}]*height:\s*300px/s,
    'the fixed 440px topology canvas shrinks on short screens',
  );
});
