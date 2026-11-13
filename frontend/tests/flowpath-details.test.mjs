import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const [topology, topologyEdges, workspace, api, panel, viewer, resize, css, viewerCss, vite] = await Promise.all([
  readFile(new URL('../src/TopologyMap.tsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/TopologyEdges.tsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/WorkspaceView.tsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/workspaceApi.ts', import.meta.url), 'utf8'),
  readFile(new URL('../src/FlowpathDetailPanel.tsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/FlowpathGeometryViewer.tsx', import.meta.url), 'utf8').catch(() => ''),
  readFile(new URL('../src/PanelResizeHandle.tsx', import.meta.url), 'utf8'),
  readFile(new URL('../src/styles/chat-responsive.css', import.meta.url), 'utf8'),
  readFile(new URL('../src/styles/flowpath-inspector.css', import.meta.url), 'utf8').catch(() => ''),
  readFile(new URL('../vite.config.ts', import.meta.url), 'utf8'),
]);

test('flowpath lines are mouse and keyboard inspectable with a forgiving hit target', () => {
  assert.match(topology, /TopologyEdges/);
  assert.match(topologyEdges, /className="topo-edge-hit"/);
  assert.match(topologyEdges, /role="button"/);
  assert.match(topologyEdges, /aria-label=\{`Inspect flowpath/);
  assert.match(topologyEdges, /onKeyDown=\{\(event\) =>/);
  assert.match(css, /\.topo-edge \.topo-edge-hit\s*\{[^}]*stroke-width:\s*22/s);
  assert.match(css, /\.topo-edge:focus-visible \.topo-edge-line/);
});

test('schema v2 exposes path-free endpoint and stable section identity records', () => {
  assert.match(api, /schema_version:\s*2/);
  assert.match(api, /interface FlowpathSection/);
  assert.match(api, /section_index:\s*number/);
  assert.match(api, /pipe_section_index:\s*number/);
  assert.match(api, /chainage_start_m:\s*number/);
  assert.match(api, /start:\s*FlowpathPoint/);
  assert.doesNotMatch(api, /resolved_path|command|stdout|stderr/);
});

test('flowpath selection opens a split beside the map with an explicit return path', async () => {
  assert.match(topology, /flowpath-split/);
  assert.doesNotMatch(topology, /flowpath-studio-open/, 'the map is not replaced');
  assert.match(topology, /<svg/, 'the map stays mounted beside the detail');
  assert.match(topology, /<TopologyInspector/, 'the split renders the inspector');
  assert.match(panel, /t\('flowpath\.back'\)/);
  assert.match(panel, /FlowpathGeometryViewer/);
  assert.match(viewer, /\['plan', 'elevation', 'side', 'isometric'\]/);
  assert.match(viewer, /t\('flowpath\.elevationAria'\)/);
  assert.match(viewer, /t\('flowpath\.fitView'\)/);
  assert.match(viewer, /data-section-index/);
  assert.match(viewer, /Math\.hypot/);
  assert.match(viewer, /<circle[\s\S]*?className="flowpath-section-hit"/);
  assert.match(viewer, /transitionSectionSelection/);
  assert.match(viewer, /flowpath-pipe-legend/);
  assert.match(viewer, /getBoundingClientRect/);
  assert.match(viewer, /setView\(profileOnly \? 'elevation' : defaultFlowpathView\(sections\)\)/);
  assert.doesNotMatch(viewer, /dangerouslySetInnerHTML/);
});

test('the flowpath split resizes toward the map side', async () => {
  assert.match(panel, /direction="grow-left"/);
  assert.match(panel, /olga_flowpath_details_open/);
  assert.match(panel, /onToggle=/);
  assert.match(resize, /direction\?:\s*'grow-right'\s*\|\s*'grow-left'/);
  assert.match(viewerCss, /\.flowpath-studio/);
  assert.match(viewerCss, /\.flowpath-summary-drawer/);
  assert.match(viewerCss, /\.flowpath-toolbar\s*\{[^}]*flex-wrap:\s*wrap/);
  assert.match(viewerCss, /prefers-reduced-motion/);
});

test('selected flowpaths load bounded path-free geometry through the authenticated API', () => {
  assert.match(api, /apiFetch\('\/api\/genkey\/flowpath-details'/);
  assert.match(api, /JSON\.stringify\(\{ rel, flowpath \}\)/);
  assert.match(workspace, /flowpathRequestRef\.current\.begin\(\)/);
  assert.match(workspace, /flowpathRequestRef\.current\.isCurrent\(request\)/);
  assert.match(panel, /Pipes/);
  assert.match(panel, /Sections/);
  assert.match(panel, /Diameter/);
  assert.match(panel, /section_range/);
  assert.doesNotMatch(panel, /resolved_path|command|\/private\//);
  assert.match(vite, /assertLoopbackOrigin/);
  assert.match(vite, /127\.0\.0\.1|localhost/);
});
