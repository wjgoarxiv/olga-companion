import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test('workspace hydration survives StrictMode setup-cleanup-setup without activating the case', async () => {
  const workspace = await import('../src/workspaceCaseOpen.mjs');
  assert.equal(typeof workspace.createWorkspaceHydration, 'function', 'a behavioral hydration coordinator exists');

  const selectedCase = { name: 'case.genkey', rel: 'case.genkey', suffix: '.genkey', size: 10 };
  const first = deferred();
  const second = deferred();
  const activations = [];
  const topologyLoads = [];
  const accepted = [];
  const errors = [];
  const loading = [];
  const pending = [first, second];
  const hydration = workspace.createWorkspaceHydration(
    {
      activate: (rel) => { activations.push(rel); },
      fetchTopology: (rel) => {
        topologyLoads.push(rel);
        return pending.shift().promise;
      },
    },
    {
      onStart: () => { loading.push(true); },
      onSuccess: (topology) => { accepted.push(topology.path); },
      onError: (error) => { errors.push(error.message); },
      onSettled: () => { loading.push(false); },
    },
  );

  const firstSetup = hydration.setup(selectedCase);
  firstSetup.cleanup();
  const secondSetup = hydration.setup(selectedCase);

  first.resolve({ path: 'stale', nodes: [], edges: [], counts: { nodes: 0, flowpaths: 0, edges: 0 }, truncated: false });
  await firstSetup.task;
  assert.deepEqual(accepted, [], 'the cleaned-up setup cannot commit stale topology');
  assert.deepEqual(loading, [true, true], 'stale settlement cannot clear the replay loading state');

  second.resolve({ path: 'current', nodes: [], edges: [], counts: { nodes: 0, flowpaths: 0, edges: 0 }, truncated: false });
  await secondSetup.task;
  assert.deepEqual(accepted, ['current']);
  assert.deepEqual(errors, []);
  assert.deepEqual(loading, [true, true, false], 'the current replay always leaves loading');
  assert.deepEqual(activations, [], 'effect hydration never activates the active case again');
  assert.deepEqual(topologyLoads, ['case.genkey', 'case.genkey'], 'StrictMode replay performs one topology request per setup');
});

test('one workspace user action activates once and surfaces a current topology failure honestly', async () => {
  const { createWorkspaceHydration } = await import('../src/workspaceCaseOpen.mjs');
  assert.equal(typeof createWorkspaceHydration, 'function');
  const selectedCase = { name: 'case.genkey', rel: 'case.genkey', suffix: '.genkey', size: 10 };
  const activations = [];
  let topologyLoads = 0;
  const errors = [];
  const loading = [];
  const hydration = createWorkspaceHydration(
    {
      activate: (rel) => { activations.push(rel); },
      fetchTopology: async () => {
        topologyLoads += 1;
        throw new Error('topology unavailable');
      },
    },
    {
      onStart: () => { loading.push(true); },
      onSuccess: () => {},
      onError: (error) => { errors.push(error.message); },
      onSettled: () => { loading.push(false); },
    },
  );

  await hydration.activate(selectedCase);

  assert.deepEqual(activations, ['case.genkey']);
  assert.equal(topologyLoads, 1);
  assert.deepEqual(errors, ['topology unavailable']);
  assert.deepEqual(loading, [true, false]);
});

test('workspace effect hydration is keyed by the active relative case, not refreshed array identity', async () => {
  const view = await read('../src/WorkspaceView.tsx');

  assert.match(view, /const hydrationCase = cases\.find\(/);
  assert.match(view, /const hydrationRel = hydrationCase\?\.rel \?\? null/);
  assert.match(view, /useEffect\(\(\) => \{[\s\S]*hydrationRef\.current\?\.setup\(hydrationCase\)[\s\S]*\}, \[hydrationRel\]\)/);
  assert.doesNotMatch(view, /\}, \[cases, activeCase\]\)/, 'equivalent context refreshes must not restart topology hydration');
});

test('768px stacked layout keeps results chart and table inside the viewport', async () => {
  // The 390px full-resolution viewport is dropped: at 768px the plot tab
  // stacks picker over chart and only the chart viewport pans horizontally.
  const [css, chart] = await Promise.all([
    read('../src/styles/results.css'),
    read('../src/TrendChart.tsx'),
  ]);
  const mobileStart = css.indexOf('@media (max-width: 760px)');
  const mobile = css.slice(mobileStart);

  assert.ok(mobileStart >= 0);
  assert.match(mobile, /\.rv-main\s*\{[^}]*overflow-y:\s*auto[^}]*overflow-x:\s*hidden/s, 'Results main owns vertical scrolling without horizontal overflow');
  assert.match(mobile, /\.rv-plot\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s, 'the plot tab stacks picker over chart under the breakpoint');
  assert.match(mobile, /\.rv-filter,[\s\S]*?max-width:\s*100%/s, 'picker controls never exceed the narrow viewport');
  assert.match(chart, /className="trend-viewport"/, 'the chart has a dedicated full-resolution viewport');
  assert.match(mobile, /\.trend-viewport\s*\{[^}]*overflow-x:\s*auto/s, 'only the chart viewport pans horizontally');
  assert.match(mobile, /\.trend-svg\s*\{[^}]*width:\s*920px[^}]*min-width:\s*920px[^}]*max-width:\s*none/s, 'mobile preserves the authored chart scale instead of shrinking labels');
  assert.match(mobile, /\.trend-mobile-hint\s*\{[^}]*display:\s*block/s, 'mobile operators are told how to inspect the full scale');
});

test('768px stacked layout keeps topology labels and counts inside the viewport', async () => {
  const [css, wb, topology, inspector] = await Promise.all([
    read('../src/styles/chat-responsive.css'),
    read('../src/styles/workbench.css'),
    read('../src/TopologyMap.tsx'),
    read('../src/TopologyInspector.tsx'),
  ]);
  const mobileStart = css.indexOf('@media (max-width: 760px)');
  const mobile = css.slice(mobileStart);

  assert.ok(mobileStart >= 0);
  assert.match(css, /\.topo-node\.is-flowpath \.topo-node-label\s*\{[^}]*fill:\s*var\(--ink-2\)/s, 'flowpath names keep contrast on theme tokens');
  assert.match(css, /\.topo-edge-label\s*\{[^}]*fill:\s*var\(--ink\)/s, 'edge labels keep contrast on theme tokens');
  assert.match(css, /\.topo-canvas\s*\{[^}]*overflow:\s*hidden/s, 'the canvas never scrolls sideways');
  assert.match(wb, /@media \(max-width:\s*760px\)[\s\S]*?\.topo-wrap\.flowpath-split \.topo-canvas\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s, 'the split stacks to one column under the breakpoint');
  assert.match(css, /@media \(max-width:\s*768px\), \(pointer:\s*coarse\)\s*\{\s*\.topo-touch-list\s*\{[^}]*display:\s*grid/s, 'touch targets stack below the canvas');
  assert.match(css, /\.topo-wrap\s*\{[^}]*position:\s*relative/s, 'selected detail is anchored to the visible topology surface');
  assert.match(css, /\.topo-detail-row\s*\{[^}]*word-break:\s*normal[^}]*overflow-wrap:\s*anywhere/s, 'technical flowpath names wrap at natural separators before splitting tokens');
  assert.match(topology, /<TopologyInspector/, 'detail is delegated after the scrollable canvas');
  assert.match(inspector, /className="topo-detail"/, 'the inspector owns the visible detail card');
  assert.match(topology, /tabIndex=\{0\}/, 'topology entities are keyboard reachable');
  assert.match(topology, /onKeyDown=/, 'topology detail can be opened from the keyboard');
});

test('comfortable density keeps 44px touch targets; compact (the default) uses 32px', async () => {
  const [baseCss, chromeCss, runCss, workspaceCss, sessionMenu] = await Promise.all([
    read('../src/styles/base.css'),
    read('../src/styles/chrome.css'),
    read('../src/styles/run.css'),
    read('../src/styles/workspace.css'),
    read('../src/SessionMenu.tsx'),
  ]);
  assert.match(baseCss, /\[data-density="comfortable"\][\s\S]*?--tgt:\s*calc\(44px \* var\(--ui-scale\)\)/, 'comfortable-density target token is 44px');
  assert.match(baseCss, /--ctl-h:\s*calc\(32px \* var\(--ui-scale\)\)/, 'control height is the token value');
  assert.match(baseCss, /:root\s*\{[^]*?--tgt:\s*calc\(32px \* var\(--ui-scale\)\)/, 'compact is the default, 32px (owner decision N3)');
  assert.match(sessionMenu, /className="session-menu"[\s\S]*className="session-rail-toggle"/, 'Chats uses a dedicated history-rail trigger inside SessionMenu');
  const chromeMobile = chromeCss.slice(chromeCss.indexOf('@media (max-width: 760px)'));
  const runMobile = runCss.slice(runCss.indexOf('@media (max-width: 760px)'));
  const workspaceMobile = workspaceCss.slice(workspaceCss.indexOf('@media (max-width: 760px)'));
  assert.match(chromeMobile, /\.conn\s*\{[^}]*min-(?:height|block-size):\s*44px/s);
  assert.match(chromeMobile, /\.chrome-select\s*\{[^}]*min-(?:height|block-size):\s*44px/s);
  const sessionRailCss = await read('../src/styles/session-rail.css');
  const sessionRailMobile = sessionRailCss.slice(sessionRailCss.indexOf('@media (max-width: 760px)'));
  assert.match(sessionRailMobile, /\.session-rail-toggle\s*\{[^}]*min-(?:height|block-size):\s*44px[^}]*max-width:\s*100%/s, 'Chats trigger is touch-safe and width-bounded');
  assert.match(runMobile, /\.run-runtime-field select\s*\{[^}]*min-(?:height|block-size):\s*44px/s);
  assert.match(workspaceMobile, /\.ws-files\s+\.ws-file\s*\{[^}]*min-(?:height|block-size):\s*44px[^}]*max-width:\s*100%/s, 'Workspace file rows are touch-safe and width-bounded');
  assert.match(chromeCss, /@media \(max-width:\s*420px\)[^]*?\.env-popover\s*\{[^}]*top:\s*calc\(var\(--compact-statusbar-height\) \+ 4px\)/s, 'diagnostics follows the shared narrow-header height');
});
