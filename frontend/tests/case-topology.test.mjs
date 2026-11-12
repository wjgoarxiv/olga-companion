import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('topology toolbar offers fit, zoom, fullscreen and a minimap toggle', async () => {
  const [map, ko, en] = await Promise.all([
    read('../src/TopologyMap.tsx'),
    read('../src/i18n/ko.ts'),
    read('../src/i18n/en.ts'),
  ]);
  for (const key of ['topo.fit', 'topo.zoomIn', 'topo.zoomOut', 'topo.fullscreen', 'topo.minimap']) {
    assert.ok(ko.includes(`'${key}':`), `ko labels the toolbar: ${key}`);
    assert.ok(en.includes(`'${key}':`), `en labels the toolbar: ${key}`);
  }
  assert.match(map, /role="toolbar"/, 'toolbar keeps its role');
  assert.match(map, /fitContentView\(/, 'fit reuses the fitted content view');
  assert.match(map, /requestFullscreen/, 'fullscreen uses the Fullscreen API');
  assert.match(map, /document\.fullscreenElement|fullscreenchange/, 'fullscreen state is tracked');
  assert.match(map, /minimap/i, 'minimap toggle exists');
});

test('topology fit and zoom handlers scale the view without executing anything', async () => {
  const map = await read('../src/TopologyMap.tsx');
  assert.match(map, /setView\(fitContentView\(/, 'fit resets the viewBox to the content');
  assert.match(map, /setView\(\(v\) =>/, 'zoom derives the next view from the current one');
  assert.doesNotMatch(map, /executeApproval|runExecute|session\.execute/, 'toolbar never executes');
});

test('topology nodes show full labels with tooltips and pixel kind symbols', async () => {
  const map = await read('../src/TopologyMap.tsx');
  assert.doesNotMatch(map, /slice\(0, 15\)/, 'the 15-character cut is gone');
  assert.match(map, /<title>/, 'nodes expose full labels to tooltips and assistive tech');
  assert.match(map, /<PixelIconInSvg/, 'nodes render pixel kind symbols');
  assert.doesNotMatch(map, /<image/, 'no 3D render image in the map');
});

test('topology counts render once beside the map', async () => {
  const [map, workspace] = await Promise.all([
    read('../src/TopologyMap.tsx'),
    read('../src/WorkspaceView.tsx'),
  ]);
  assert.match(map, /topo-meta/, 'counts live in the map footer');
  assert.doesNotMatch(workspace, /ws-canvas-meta[\s\S]*pickCountKey/, 'counts are not repeated in the canvas head');
});

test('flowpath selection opens a split beside the map instead of replacing it', async () => {
  const [map, css] = await Promise.all([
    read('../src/TopologyMap.tsx'),
    read('../src/styles/workbench.css'),
  ]);
  assert.match(map, /<svg/, 'the map stays mounted when an edge is selected');
  assert.match(map, /TopologyInspector/, 'the inspector renders beside the map');
  assert.match(map, /flowpath-split/, 'split layout marker exists');
  assert.match(css, /flowpath-split/, 'split layout has a style contract');
  assert.match(map, /t\('flowpath\.back'\)|<TopologyInspector/, 'the split keeps an explicit return path');
});

test('problems can focus their topology node', async () => {
  const map = await read('../src/TopologyMap.tsx');
  assert.match(map, /FOCUS_TOPOLOGY_NODE_EVENT|parseFocusNodeEvent/, 'map listens for problem focus requests');
});

test('validation shows a still scanner rule over the map (no sweep, no animation)', async () => {
  const [map, workspace, css] = await Promise.all([
    read('../src/TopologyMap.tsx'),
    read('../src/WorkspaceView.tsx'),
    read('../src/styles/workbench.css'),
  ]);
  assert.match(workspace, /scanning=\{loading \|\| tabLoading\}/, 'loads drive the scanner');
  assert.match(map, /\{scanning && <div className="topo-scanner"/, 'scanner overlays the canvas');
  assert.match(css, /\.topo-scanner\s*\{[^}]*height:\s*2px/s, 'the cue is a 2 px rule');
  assert.doesNotMatch(css, /\.topo-scanner[^{]*\{[^}]*animation/s, 'it does not animate');
  assert.doesNotMatch(css, /@keyframes topo-scan\b/, 'no sweep keyframes');
});

test('topology motion is gated: flow dashes and snap; no outline pulse (static Terminalcore)', async () => {
  const [map, css] = await Promise.all([
    read('../src/TopologyMap.tsx'),
    read('../src/styles/workbench.css'),
  ]);
  assert.doesNotMatch(css, /topo-edge-line[^{]*\{[^}]*(?:stroke-dasharray|animation)/s, 'edges are plain still lines in every preset');
  assert.doesNotMatch(css, /@keyframes topo-flow\b/, 'no marching-ants keyframes');
  assert.match(css, /html\[data-motion="full"\] \.topo-node\s*\{[^}]*transition:[^}]*var\(--d-snap\)/s, 'selection snaps in Full');
  assert.doesNotMatch(map, /setPulseNode|pulseNode|motionAllowsFull/, 'the topology map no longer pulses a focused node');
  assert.doesNotMatch(css, /topo-pulse|\.topo-node\.pulse/, 'no pulse keyframes or rule');
});

test('inspector numbers roll through a motion-gated component', async () => {
  const [rolling, panel] = await Promise.all([
    read('../src/ui/RollingNumber.tsx'),
    read('../src/FlowpathDetailPanel.tsx'),
  ]);
  assert.match(rolling, /motionAllowsFull/, 'rolling respects the motion setting');
  assert.match(rolling, /\.animate\b/, 'rolling uses Web Animations, transform only');
  assert.match(panel, /<RollingNumber/, 'flowpath metrics roll');
});
