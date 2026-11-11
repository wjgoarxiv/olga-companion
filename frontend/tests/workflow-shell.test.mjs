import { readFile, readdir } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { translate } from '../src/i18n/index.ts';
import { readResultsSource } from './results-source.mjs';
import { readRunSource } from './run-source.mjs';
import { readSessionSource } from './session-source.mjs';

const read = (p) => readFile(new URL(p, import.meta.url), 'utf8');
const sourceRoot = new URL('../src/', import.meta.url);
const sourceSuffixes = ['.css', '.js', '.mjs', '.ts', '.tsx'];
async function readSourceFiles(dir = sourceRoot) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    if (entry.isDirectory()) {
      files.push(...await readSourceFiles(new URL(entry.name + '/', dir)));
    } else if (sourceSuffixes.some((suffix) => entry.name.endsWith(suffix))) {
      const url = new URL(entry.name, dir);
      files.push({ path: url.pathname, text: await readFile(url, 'utf8') });
    }
  }
  return files;
}
const readCss = async () => {
  const root = await read('../src/styles.css');
  const imports = [...root.matchAll(/@import ['"](.+)['"];/g)];
  const imported = await Promise.all(imports.map((m) => read(`../src/${m[1]}`)));
  return [root, ...imported].join('\n');
};

test('app shell: workbench grid regions (title, activity, explorer, centre, dock, panel, status)', async () => {
  const [wb, css, app] = await Promise.all([
    read('../src/styles/workbench.css'),
    readCss(),
    read('../src/App.tsx'),
  ]);
  assert.match(wb, /\.wb\s*\{[^}]*height:\s*100dvh/s, 'the shell is a fixed-viewport grid');
  assert.match(
    wb,
    /grid-template-areas:\s*"activity explorer exhandle centre dock"\s*"activity explorer exhandle panel dock"/s,
    'title bar, activity, explorer, resizer, centre, dock, panel and status occupy their named areas',
  );
  assert.match(wb, /\.wb-mid\s*\{[^}]*grid-template-columns:[^}]*minmax\(0,\s*1fr\)/s, 'the centre column yields instead of forcing horizontal overflow');
  assert.match(wb, /\.wb-titlebar\s*\{[^}]*height:\s*var\(--tb-h\)/s, 'the title bar follows the frame token');
  assert.match(css, /\.wb-status\s*\{[^}]*height:\s*var\(--sb-h\)/s, 'the status bar follows the frame token');
  assert.match(wb, /\.wb-activity \.ui-iconbutton\s*\{[^}]*width:\s*44px/s, 'comfortable density keeps 44px activity targets');
  assert.match(
    wb,
    /@media \(max-width: 768px\)[\s\S]*?grid-template-areas:\s*"activity"\s*"explorer"\s*"centre"\s*"dock"\s*"panel"/s,
    'narrow viewports stack every region in focus order',
  );
  assert.match(css, /\.empty-hero\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s*;/s, 'empty Chat starts with one task-focused column');
  assert.match(css, /\.starter-groups\s*\{[^}]*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/s, 'desktop empty Chat starters are grouped into stable workflow columns');
  assert.match(css, /\.timeline\s*\{[^}]*overflow-y:\s*auto/s, 'the chat timeline is still a scroll region');
  assert.match(app, /<div className="wb">/, 'the frame is the workbench shell, not one chat column');
  assert.match(app, /<ActivityBar view=\{view\} onSelect=\{selectView\}[^>]*>/, 'the activity rail routes through the persistent selector');
  assert.match(app, /<main ref=\{workbenchRef\} id="primary-workbench"/, 'the workbench owns focus + its own region');
  const chat = await read('../src/ChatView.tsx');
  assert.match(chat, /timeline\.length === 0[\s\S]*?scrollTo\(\{ top: 0/s, 'empty starter timeline starts at top instead of bottom-scrolling');
  assert.match(chat, /'timeline' \+ \(props\.timeline\.length === 0 \? ' empty' : ''\)/, 'empty Chat timeline gets density-specific layout');
  assert.doesNotMatch(app, /className="app"|className="topbar"|<Sidebar /, 'the single-column top-bar frame is replaced');
});

test('chat surface is extracted from the app orchestrator', async () => {
  const app = await read('../src/App.tsx');
  const chat = await read('../src/ChatView.tsx');
  const timeline = await read('../src/timeline.ts');
  const appCodeLines = app.split('\n').filter((line) => line.trim() && !line.trim().startsWith('//')).length;
  assert.ok(appCodeLines <= 250, `App.tsx should stay <=250 pure LOC, got ${appCodeLines}`);
  assert.match(app, /<ChatDockView\b/, 'App delegates the chat surface to the dock');
  assert.match(app, /useChatController/, 'App delegates chat runtime control');
  assert.doesNotMatch(app, /<section className="chat"/, 'App no longer owns chat DOM details');
  assert.match(chat, /aria-label=\{t\('chat\.conversation'\)\}/, 'the extracted chat component owns the conversation landmark');
  assert.match(chat, /<SessionMenu /, 'chat session controls moved with the chat header');
  assert.match(timeline, /export type TimelineItem/, 'timeline variant ownership is isolated');
  assert.match(timeline, /rehydrateTimeline/, 'history rehydration lives with timeline types');
});

test('chat controller delegates cohesive session and scroll state below the source-size ceiling', async () => {
  // Given the controller source that coordinates chat runtime behavior.
  const controller = await read('../src/useChatController.ts');

  // When its non-blank, non-comment source lines are counted.
  const codeLines = controller.split('\n').filter((line) => line.trim() && !line.trim().startsWith('//')).length;

  // Then the orchestrator remains reviewable and delegates its independent state owners.
  assert.ok(codeLines <= 250, `useChatController.ts should stay <=250 pure LOC, got ${codeLines}`);
  assert.match(controller, /useChatSessions/, 'session registry and history lifecycle have a dedicated hook');
  assert.match(controller, /useChatScroll/, 'chat viewport state has a dedicated hook');
});

test('chat bootstrap is idempotent under React StrictMode', async () => {
  const main = await read('../src/main.tsx');
  const sessions = await read('../src/useChatSessions.ts');
  const navigation = await read('../src/chatNavigation.mjs');
  assert.match(main, /<React\.StrictMode>/, 'dev renders effects twice');
  assert.match(sessions, /navigatorRef\.current \?\?= createChatNavigator/, 'one navigator survives StrictMode re-renders');
  assert.match(navigation, /createPending/, 'first-send creation promise is memoized');
  assert.match(navigation, /createPending \?\?= startCreate/, 'the first message creates one session');
  assert.match(navigation, /ports\.createSession\(chatTitle\(titleHint\)\)/, 'creation goes through the one memoized path');
  const bootstrap = navigation.slice(
    navigation.indexOf('async startInitial'),
    navigation.indexOf('newChat()'),
  );
  assert.doesNotMatch(bootstrap, /createSession/, 'opening or reloading is read-only');
});

test('results view: interactive .tpl trend chart (self-contained SVG + pyfas series)', async () => {
  const rv = await readResultsSource(import.meta.url);
  // The plot tab owns the chart and the whole-variable pick path.
  const plotTab = await read('../src/ResultPlotTab.tsx');
  assert.match(rv, /fetchSeries/, 'fetches a variable time series');
  assert.match(plotTab, /TrendChart/, 'renders it as a chart');
  assert.match(rv, /exportPublicationPlot/, 'exports a publication-quality plot through the result API');
  assert.match(rv, /series\.analysis/, 'shows deterministic result interpretation');
  assert.match(plotTab, /pickVar\(v\)/, 'passes the selected position, not only a duplicate-prone variable name');
  assert.match(rv, /onOpenRun/, 'empty results can route the operator to Run');
  assert.match(rv, /WorkbenchPrompt[\s\S]*?<Button variant="primary" onClick=\{onOpenRun\}>\{t\('results\.openRun'\)\}<\/Button>/s, 'empty results has a real action, not just a passive note');
  assert.match(rv, /rv-view\$\{results\.length === 0 && !error \? ' empty' : ''\}/, 'empty results marks the full workbench state');
  assert.match(rv, /rv-list-empty/, 'empty results rail is a compact status row, not a blank rail');
  assert.match(rv, /WorkbenchPrompt/, 'empty results uses the shared production prompt');
  assert.match(rv, /'rv-main' \+ \(!selected && !error && results\.length === 0 \? ' empty' : ''\)/, 'empty results promotes the review pane into an anchored surface');
  assert.match(rv, /contextLabel=\{t\('results\.emptyContext'\)\}/, 'empty results exposes output scan status');
  assert.match(rv, /workbench-prompt-footer/, 'empty results groups the run action with its status note');
  assert.match(rv, /workbench-prompt-steps/, 'empty results explains the next operator steps');
  const tc = await read('../src/TrendChart.tsx');
  assert.match(tc, /<svg/, 'a self-contained SVG chart');
  assert.doesNotMatch(tc, /recharts|uplot|chart\.js|["']d3["']/i, 'no charting dependency');
  const s = await readSessionSource(import.meta.url);
  assert.match(s, /\/api\/results\/series/, 'the JSON series endpoint');
  assert.match(s, /\/api\/results\/plot/, 'the publication plot endpoint');
  assert.match(s, /position/, 'series and plot requests preserve OLGA position identity');
  const centre = await read('../src/shell/CentreViews.tsx');
  assert.match(centre, /<ResultsView[\s\S]*?onOpenRun=\{onOpenRun\}/, 'Results empty state routes to the real Run view');
  const css = await readCss();
  assert.match(css, /\.trend-wrap\s*\{[^}]*font-family:\s*var\(--font-ui\)/, 'result graphics use the embedded UI family token (Meslo, Pretendard for Korean)');
  assert.match(css, /\.rv-view\.empty\s*\{[^}]*grid-template-columns:\s*auto 8px minmax\(0,\s*1fr\)/s, 'desktop empty Results keeps the rail resizable without wasting width');
  assert.match(css, /\.rv-main\.empty\s*\{[^}]*align-items:\s*flex-start/s, 'desktop empty Results review surface is anchored beside the rail');
  assert.match(css, /\.rv-main\.empty > \.workbench-prompt\s*\{[^}]*margin:\s*0/s, 'empty Results prompt must not float in the center of blank space');
  assert.match(css, /\.workbench-prompt-context\s*\{[^}]*display:\s*grid/s, 'empty Results context is a compact output readout');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.rv-view\s*\{[\s\S]*?grid-template-columns:\s*1fr[\s\S]*?grid-template-rows:\s*minmax\(120px,\s*34vh\) minmax\(0,\s*1fr\)/s, 'mobile Results stacks inventory over chart');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.rv-view\.empty\s*\{[\s\S]*?grid-template-columns:\s*1fr[\s\S]*?grid-template-rows:\s*auto minmax\(0,\s*1fr\)/s, 'mobile empty Results collapses the empty output rail into one column');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.rv-main\.empty\s*\{[\s\S]*?padding:\s*14px 16px 84px/s, 'mobile empty Results keeps review action clear of bottom nav');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.workbench-prompt-hero,[\s\S]*?grid-template-columns:\s*1fr/s, 'mobile empty Results context stacks without overflow');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.rv-body\s*\{[\s\S]*?grid-template-columns:\s*1fr/s, 'mobile Results variable/chart layout stacks');
});

test('workspace view: one explorer list + persistent topology canvas (topology outside chat)', async () => {
  const [wv, explorer] = await Promise.all([
    read('../src/WorkspaceView.tsx'),
    read('../src/shell/ExplorerPanel.tsx'),
  ]);
  const labels = await read('../src/workspaceLabels.ts');
  assert.match(wv, /fetchTopology/, 'fetches the network graph directly (no chat)');
  assert.match(wv, /TopologyMap/, 'renders it on a persistent canvas');
  assert.match(explorer, /role="tree"/, 'the Explorer owns the one workspace file list');
  assert.match(explorer, /wb-explorer-item/, 'file rows live in the Explorer tree');
  assert.doesNotMatch(wv, /ws-files/, 'the centre no longer duplicates the file list');
  assert.match(wv, /onOpenSettings/, 'empty workspace can route the operator to Settings');
  assert.match(wv, /WorkbenchPrompt[\s\S]*?<Button variant="primary" onClick=\{onOpenSettings\}>\{t\('workspace\.openSettings'\)/s, 'empty workspace has a real action, not just a passive note');
  assert.equal(translate('ko', 'workspace.openSettings'), '설정 열기', 'ko settings action copy is pinned to the rendered dictionary value');
  assert.match(
    wv,
    /ws-view\$\{cases\.length === 0 \? ' empty' : !selected \? ' awaiting-selection' : ''\}/,
    'workspace marks empty inventory and awaiting-selection as distinct full-workbench states',
  );
  assert.match(explorer, /wb-explorer-empty/, 'empty inventory is a compact status row in the Explorer, not a blank rail');
  assert.match(wv, /WorkbenchPrompt/, 'empty workspace uses the shared production prompt');
  assert.match(wv, /'ws-canvas' \+ \(!selected && cases\.length === 0 \? ' empty' : ''\)/, 'empty workspace promotes the canvas into an anchored setup surface');
  assert.match(wv, /contextLabel=\{t\('workspace\.emptyContextLabel'\)/, 'empty workspace exposes scan status');
  assert.equal(translate('ko', 'workspace.emptyContextLabel'), '현재 목록', 'ko scan-status copy is pinned to the rendered dictionary value');
  assert.match(wv, /workbench-prompt-footer/, 'empty workspace keeps setup action and status grouped');
  assert.match(wv, /workbench-prompt-steps/, 'empty workspace explains the next operator steps');
  assert.doesNotMatch(wv, /\(default\)/, 'Workspace must not expose raw internal default labels');
  assert.match(wv, /workspaceRootLabel/, 'Workspace uses the shared operator-facing workspace label');
  assert.match(labels, /FALLBACK_WORKSPACE_LABEL = 'Bundled workspace'/, 'default workspace copy is production-facing');
  assert.match(labels, /normalizedRoot === '\(default\)'/, 'literal backend default sentinel is normalized before rendering');
  const css = await readCss();
  assert.match(css, /\.ws-view\s*\{[^}]*display:\s*block/s, 'desktop workspace is a single column: the Explorer owns the list, the canvas takes the freed width');
  assert.match(css, /\.ws-canvas\.empty\s*\{[^}]*align-items:\s*flex-start/s, 'desktop empty workspace setup is anchored in the freed canvas');
  assert.match(css, /\.ws-canvas\.empty > \.workbench-prompt,[\s\S]*?\.rv-main\.empty > \.workbench-prompt\s*\{[^}]*margin:\s*0/s, 'empty workspace prompt must not float in the center of blank space');
  assert.match(css, /\.workbench-prompt-context\s*\{[^}]*display:\s*grid/s, 'empty workspace context is a compact workbench readout');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.ws-view,\s*\.ws-view\.empty,\s*\.ws-view\.awaiting-selection\s*\{\s*display:\s*block/s, 'mobile workspace stays a single column in every state with no duplicate rail');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.ws-canvas\.empty\s*\{[\s\S]*?padding:\s*14px 16px 84px/s, 'mobile empty workspace keeps setup controls clear of bottom nav');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.workbench-prompt-hero,[\s\S]*?grid-template-columns:\s*1fr/s, 'mobile empty workspace context stacks without overflow');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.ws-canvas-head\s*\{[\s\S]*?flex-wrap:\s*wrap/s, 'mobile workspace metadata wraps');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.workspace-popover\s*\{[\s\S]*?position:\s*fixed[\s\S]*?left:\s*10px[\s\S]*?right:\s*10px/s, 'mobile workspace picker is pinned to viewport insets with no horizontal overflow');
  const centre = await read('../src/shell/CentreViews.tsx');
  assert.match(centre, /<WorkspaceView[\s\S]*?onOpenSettings=\{onOpenSettings\}/, 'Workspace empty state routes to Settings');
  const s = await readSessionSource(import.meta.url);
  assert.match(s, /\/api\/genkey\/topology/, 'the direct topology route');
});

test('activity bar switches named views; each is a real mounted view', async () => {
  const [app, rail, centre] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/ActivityBar.tsx'),
    read('../src/shell/CentreViews.tsx'),
  ]);
  for (const v of ['workspace', 'results', 'run', 'settings']) {
    assert.match(rail, new RegExp(`view: '${v}'`), `activity bar has ${v}`);
  }
  assert.match(rail, /pressed=\{entry\.view === view\}/, 'the active view is marked for a11y');
  assert.match(rail, /<PixelIcon name=\{entry\.icon\}/, 'views are identified by their pixel icon');
  assert.match(rail, /wb-activity-indicator/, 'one indicator tracks the active view');
  assert.match(app, /<ActivityBar view=\{view\} onSelect=\{selectView\}/, 'the rail routes through the persistent selector');
  assert.match(centre, /<WorkspaceView[\s>]/);
  assert.match(centre, /<ResultsView /);
  assert.match(centre, /<RunView /);
  assert.match(centre, /<SettingsView /);
});

test('app shell: selected workflow view persists across reloads with a safe fallback', async () => {
  const [store, app] = await Promise.all([
    read('../src/shell/useWorkbenchLayout.ts'),
    read('../src/App.tsx'),
  ]);
  assert.match(store, /export type WorkbenchView = 'workspace' \| 'results' \| 'run' \| 'settings'/, 'view state is a typed workflow union');
  assert.match(store, /const WORKBENCH_LAYOUT_KEY = 'olga-companion\.workbench-layout\.v1'/, 'the layout has a stable storage key');
  assert.match(store, /function isWorkbenchView\(value: unknown\): value is WorkbenchView/, 'stored values are checked before entering view state');
  assert.match(store, /export function loadWorkbenchLayout\(\): WorkbenchLayout/, 'stored layout is parsed at the boundary');
  assert.match(store, /const carried = readLegacyView\(\)/, 'the legacy view key is read once and carried over');
  assert.match(store, /writeLocalStorage\(WORKBENCH_LAYOUT_KEY, JSON\.stringify\(layout\)\)/, 'layout changes are persisted through the safe boundary');
  assert.match(store, /export function saveWorkbenchLayout\(layout: WorkbenchLayout\): void/, 'layout writes are isolated behind a boundary');
  assert.match(store, /readLocalStorage\(WORKBENCH_LAYOUT_KEY\)/, 'read failures resolve through the safe storage boundary');
  assert.match(store, /readLocalStorage\(LEGACY_VIEW_KEY\)/, 'the legacy key resolves through the same safe boundary');
  assert.match(store, /saveWorkbenchLayout\(next\)/, 'persistent routing uses the exception-safe writer');
  assert.match(app, /<ActivityBar view=\{view\} onSelect=\{selectView\}/, 'rail selection routes through the persistent selector');
  assert.doesNotMatch(app, /setView|VIEW_STORAGE_KEY/, 'nothing bypasses the layout store');
});

test('run view: preview -> run (human approval) -> live status -> real cancel', async () => {
  const rv = await readRunSource();
  assert.match(rv, /onOpenWorkspace/, 'empty Run can route the operator to Workspace');
  assert.match(rv, /WorkbenchPrompt[\s\S]*?t\('run\.openWorkspace'\)/s, 'empty Run has a real action, not just a passive note');
  assert.match(rv, /runExecute/, 'the Run click is the human approval');
  assert.match(rv, /runStatus/, 'live status polling');
  assert.match(rv, /runCancel/, 'Stop actually cancels the process');
  assert.match(rv, /sweepPreview/, 'batch sweep preview is available in Run view');
  assert.match(rv, /sweepExecute/, 'batch sweep execution is a human approval');
  assert.match(rv, /sweepStatus/, 'batch sweep live status polling');
  assert.match(rv, /sweepCancel/, 'batch Stop cancels all child runs');
  assert.match(rv, /window\.setTimeout\(\(\) => \{ void tick\(\); \}, 1500\)/, 'polls without overlapping status requests');
  assert.doesNotMatch(rv, /setInterval/, 'status polling cannot overlap interval ticks');
  assert.match(rv, /<Segmented/, 'single-run and sweep share the accessible Segmented control');
  assert.match(rv, /ariaLabel=\{t\('run\.modeLabel'\)\}/, 'the mode switch keeps its accessible name');
  assert.match(rv, /t\('run\.advancedSweep'\)/, 'parametric sweep keeps its advanced label');
  assert.match(rv, /run-panel/, 'Run view has production-density workflow panels');
  assert.doesNotMatch(rv, /run-readiness/, 'the case, engine and sandbox are stated once each, not in a repeating card strip');
  assert.match(rv, /RunStatePill/, 'run state keeps its single shared pill in the Run tab');
  assert.match(rv, /RunSweepStatus/, 'sweep status is extracted from the near-ceiling Run view');
  assert.doesNotMatch(rv, /Run id/, 'Run view does not expose debug-like run-id table headers');
  const css = await readCss();
  assert.match(css, /\.run-view\s*\{[^}]*overflow-x:\s*hidden/s, 'long run titles cannot create a horizontal scrollbar');
  assert.match(css, /\.run-title\s*\{[^}]*display:\s*block/s, 'run title is a dedicated block instead of inheriting Workspace monospace');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.run-view\s*\{[\s\S]*?padding:\s*14px 16px 84px/s, 'mobile Run keeps controls clear of bottom nav');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.run-actions\s*\{[\s\S]*?grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/s, 'mobile single-run actions keep both labels horizontally readable');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.run-head\s*\{[\s\S]*?flex-direction:\s*column/s, 'mobile Run stacks the head instead of clipping');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.run-panel\s*\{[\s\S]*?padding:\s*10px/s, 'mobile Run panels are compact enough to keep sweep controls usable');
  assert.match(css, /\.sweep-status-grid\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/s, 'sweep status cards replace the table-like run-id matrix');
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*?\.sweep-status-grid\s*\{[\s\S]*?grid-template-columns:\s*1fr/s, 'mobile sweep status cards stack without horizontal overflow');
  const s = await readSessionSource(import.meta.url);
  assert.match(s, /\/api\/run\/cancel/, 'the cancel route (was unused)');
  assert.match(s, /\/api\/sweep\/execute/, 'the sweep execute route');
  const centre = await read('../src/shell/CentreViews.tsx');
  assert.match(centre, /<RunView[\s\S]*?onOpenWorkspace=\{onOpenWorkspace\}/, 'Run empty state routes to the real Workspace view');
});

test('chat navigation reads busy from the synchronous stream ref, never the last rendered value', async () => {
  const controller = await read('../src/useChatController.ts');
  const sessions = await read('../src/useChatSessions.ts');
  const stream = await read('../src/useChatStream.ts');

  assert.match(stream, /busyRef\.current = value;\s*setBusy\(value\)/, 'the ref flips in the same call as the state');
  assert.match(controller, /useChatSessions\(\{[^}]*isBusy: stream\.isBusy/s);
  assert.match(sessions, /isBusy: \(\) => latest\.current\.isBusy\(\)/);
  assert.doesNotMatch(sessions, /latest\.current\.busy/, 'a click between a send and its re-render must not slip past the guard');
});
