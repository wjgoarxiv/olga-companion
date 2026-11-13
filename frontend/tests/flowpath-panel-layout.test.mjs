import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const routing = new URL('../src/topologyEdgeRoutes.ts', import.meta.url);

/** y of a cubic Bezier at t = 0.5 for the path routeParallelEdge returns. */
function apexY(path) {
  const numbers = path.match(/-?\d+(?:\.\d+)?/g).map(Number);
  const [, y0, , c1y, , c2y, , y3] = numbers;
  return (y0 + 3 * c1y + 3 * c2y + y3) / 8;
}

test('two parallel flowpaths bow apart by the full lane spacing at their midpoint', async () => {
  const { parallelEdgeOffsets, routeParallelEdge } = await import(routing.href);
  const offsets = parallelEdgeOffsets([
    { source: 'BOTTOM', target: 'TOP' },
    { source: 'BOTTOM', target: 'TOP' },
  ]);
  const apexes = offsets.map((offset) => apexY(
    routeParallelEdge({ x1: 150, y1: 80, x2: 300, y2: 80, offset }).path,
  ));
  assert.equal(Math.round(apexes[1] - apexes[0]), 24, 'the drawn curves are as far apart as their offsets claim');
});

test('parallel flowpath labels sit on opposite sides of the pair, clear of both strokes', async () => {
  const { parallelEdgeOffsets, routeParallelEdge } = await import(routing.href);
  const offsets = parallelEdgeOffsets([
    { source: 'BOTTOM', target: 'TOP' },
    { source: 'BOTTOM', target: 'TOP' },
  ]);
  const [upper, lower] = offsets.map((offset) => {
    const route = routeParallelEdge({ x1: 150, y1: 80, x2: 300, y2: 80, offset });
    return { apex: apexY(route.path), labelY: route.labelY };
  });
  assert.ok(upper.labelY < upper.apex, 'the upper label is above its own stroke');
  assert.ok(lower.labelY > lower.apex, 'the lower label is below its own stroke');
  assert.ok(lower.labelY - upper.labelY >= 40, 'labels never share a text line');
});

test('a single flowpath keeps its label just above the line', async () => {
  const { routeParallelEdge } = await import(routing.href);
  const route = routeParallelEdge({ x1: 0, y1: 50, x2: 100, y2: 50, offset: 0 });
  assert.equal(route.labelY, 46);
});

test('edge label hit boxes are sized from the rendered label font, not a fixed glyph width', async () => {
  const [layer, map] = await Promise.all([read('../src/TopologyEdges.tsx'), read('../src/TopologyMap.tsx')]);
  assert.match(layer, /labelFontSize/);
  assert.match(map, /labelFontSize=\{labelFs\}/);
});

test('node spacing leaves room for the longest flowpath label between ranks', async () => {
  const map = await read('../src/TopologyMap.tsx');
  assert.match(map, /rankSeparation\(/);
});

test('geometry panel: toggles and labels never wrap, and the chart gets the main share', async () => {
  const css = await read('../src/styles/flowpath-inspector.css');
  assert.match(css, /\.flowpath-toolbar button[^{]*\{[^}]*white-space:\s*nowrap/s, 'toolbar buttons stay on one line');
  assert.match(css, /\.flowpath-toolbar label\s*\{[^}]*white-space:\s*nowrap/s, 'the elevation label stays on one line');
  assert.match(css, /\.flowpath-view-switch[^{]*\{[^}]*flex:\s*0 0 auto/s, 'the projection switch never shrinks');
  assert.match(css, /\.flowpath-studio\s*\{[^}]*container:\s*flowpath-studio\s*\/\s*inline-size/s, 'the panel lays out by its own width');
  assert.match(
    css,
    /\.topo-wrap\.flowpath-split \.topo-canvas\.flowpath-split-canvas\s*\{[^}]*grid-template-columns:[^;]*minmax\(0,\s*1fr\)/s,
    'the detail column takes the full width',
  );
});

test('geometry panel: below its width threshold the details stack under the chart', async () => {
  const css = await read('../src/styles/flowpath-inspector.css');
  assert.match(css, /@container flowpath-studio \(max-width:\s*\d+px\)\s*\{[^@]*\.flowpath-studio-body\s*\{[^}]*display:\s*contents/s);
  assert.match(css, /@container flowpath-studio \(max-width:\s*\d+px\)[\s\S]*\.flowpath-drawer-resizer\s*\{[^}]*display:\s*none/s, 'no side resizer while stacked');
  assert.match(css, /@container flowpath-studio \(max-width:\s*\d+px\)[\s\S]*\.flowpath-geometry-stage\s*\{[^}]*flex:\s*1 0 \d+px/s, 'the stacked chart keeps a readable height');
});

test('the side drawer can never take more than its share of the panel', async () => {
  const css = await read('../src/styles/flowpath-inspector.css');
  assert.match(css, /\.flowpath-summary-drawer\s*\{[^}]*max-width:\s*\d+cqw/s);
});

test('an open flowpath panel replaces the map visually: the map and its toolbar are hidden, the panel fills the pane', async () => {
  const css = await read('../src/styles/flowpath-inspector.css');
  assert.match(css, /\.flowpath-split-canvas > \.topo-svg\s*\{[^}]*display:\s*none/s, 'the unreadable 5 px map strip is gone');
  assert.match(css, /\.topo-wrap\.flowpath-split \.topo-toolbar[^{]*\{[^}]*display:\s*none/s, 'map-only controls are hidden with it');
  assert.match(
    css,
    /\.topo-wrap\.flowpath-split \.topo-canvas\.flowpath-split-canvas\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\)/s,
  );
  const canvas = css.match(/\.topo-wrap\.flowpath-split \.topo-canvas\.flowpath-split-canvas\s*\{([^}]*)\}/s)[1];
  const minimum = Number(canvas.match(/min-height:\s*(\d+)px/)?.[1] ?? 0);
  assert.ok(minimum <= 400, 'the canvas never forces the workspace pane to scroll at a 600 px pane height');
  assert.doesNotMatch(css, /min-height:\s*620px/);
});

test('the geometry map is still mounted while the panel is open, so Back restores it', async () => {
  const map = await read('../src/TopologyMap.tsx');
  assert.match(map, /<svg[\s\S]*className="topo-svg"/);
  assert.match(map, /closeFlowpathStudio/);
});

test('stacked panel: the chart takes the pane height left under the header, details follow below', async () => {
  const css = await read('../src/styles/flowpath-inspector.css');
  const block = css.match(/@container flowpath-studio \(max-width:\s*759px\)\s*\{([\s\S]*?)\n\}/)[1];
  assert.match(block, /\.flowpath-studio-body\s*\{[^}]*display:\s*contents/s);
  assert.match(block, /\.flowpath-geometry-stage\s*\{[^}]*flex:\s*1 0 \d+px/s, 'the chart grows to fill the free height');
  assert.match(block, /\.flowpath-geometry-stage\s*\{[^}]*display:\s*flex/s);
  assert.doesNotMatch(block, /\.flowpath-plot\s*\{[^}]*height:\s*clamp/s, 'no fixed chart height that pushes the details up');
});

test('toolbar: projection, exaggeration and zoom share one compact row at a 450 px panel', async () => {
  const css = await read('../src/styles/flowpath-inspector.css');
  assert.match(css, /\.flowpath-toolbar\s*\{[^}]*gap:\s*(?:[0-9]|10)px[^}]*\}/s);
  const toolbar = css.match(/\.flowpath-toolbar\s*\{([^}]*)\}/s)[1];
  assert.match(toolbar, /gap:\s*6px/, 'tight gaps keep the three groups on one row');
  assert.match(css, /\.flowpath-toolbar button\s*\{[^}]*padding:\s*0 8px/s);
  assert.match(css, /\.flowpath-camera-controls\s*\{[^}]*margin-left:\s*auto/s, 'zoom sits at the end of the same row');
  assert.match(css, /\.flowpath-toolbar select\s*\{[^}]*min-width:\s*\d+px/s);
});

test('the chart is drawn at its measured pixel size so labels stay legible at any width', async () => {
  const viewer = await read('../src/FlowpathGeometryViewer.tsx');
  assert.match(viewer, /ResizeObserver/);
  assert.match(viewer, /viewBox=\{`0 0 \$\{plotWidth\} \$\{plotHeight\}`\}/);
  assert.doesNotMatch(viewer, /\bWIDTH\b|\bHEIGHT\b/, 'no fixed 960x560 canvas remains');
});

test('the toolbar and legend never shrink, so a wrapped toolbar row stays whole', async () => {
  const css = await read('../src/styles/flowpath-inspector.css');
  assert.match(css, /\.flowpath-toolbar \{[^}]*flex: 0 0 auto;/);
  assert.match(css, /\.flowpath-pipe-legend \{[^}]*flex: 0 0 auto;/);
});

test('toolbar: at 360 px and up every control fits on one row, with compact zoom buttons and no visible label under 560 px', async () => {
  const css = await read('../src/styles/flowpath-inspector.css');
  const viewer = await read('../src/FlowpathGeometryViewer.tsx');
  const height = Number(css.match(/\.flowpath-toolbar button, \.flowpath-toolbar select\s*\{[^}]*min-height:\s*(\d+)px/s)[1]);
  assert.ok(height >= 36, 'the toolbar controls stay at least 36 px tall (width, not height, is what fits the row)');
  const zoom = css.match(/\.flowpath-camera-controls button\s*\{([^}]*)\}/s)[1];
  assert.ok(Number(zoom.match(/min-width:\s*(\d+)px/)[1]) >= 32, 'a zoom button keeps a 32 px minimum target');
  assert.ok(Number(zoom.match(/padding:\s*0 (\d+)px/)[1]) <= 6, 'zoom buttons are compact');
  const switchGap = css.match(/\.flowpath-view-switch, \.flowpath-camera-controls\s*\{[^}]*gap:\s*(\d+)px/s)[1];
  assert.ok(Number(switchGap) <= 2, 'the button groups use tight gaps');
  assert.match(css, /@container flowpath-studio \(max-width:\s*559px\)\s*\{[^@]*\.flowpath-exaggeration-text\s*\{[^}]*display:\s*none/s, 'the visible label text goes below 560 px');
  assert.match(viewer, /<span className="flowpath-exaggeration-text">\{t\('flowpath\.elevation'\)\}<\/span>/, 'the label text is its own element');
  assert.match(viewer, /aria-label=\{t\('flowpath\.elevationAria'\)\}/, 'the select keeps its accessible name');
  assert.doesNotMatch(css, /\.flowpath-toolbar[^{]*\{[^}]*(?:word-break:\s*break-all|overflow-wrap:\s*anywhere)/s, 'text never wraps per character');
});
