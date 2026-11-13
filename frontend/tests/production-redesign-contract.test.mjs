import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('the shell and Results inventory share one Terminalcore type system (Meslo body, Pretendard Korean and display)', async () => {
  const [app, inventory, layout, base, statusbar, workspace, results] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/ResultsInventoryRail.tsx'),
    read('../src/ResultsPrompts.tsx'),
    read('../src/styles/base.css'),
    read('../src/styles/statusbar.css'),
    read('../src/styles/workspace.css'),
    read('../src/styles/results.css'),
  ]);

  assert.match(base, /--font-ui:\s*"Meslo LGS NF"/);
  assert.match(base, /--font-display:\s*"Pretendard Variable"/);
  assert.match(base, /font-family:\s*var\(--font-ui\)/);
  assert.match(base, /--font-mono:\s*"Meslo LGS NF"/, 'numbers, units, codes and file names read the mono token');
  assert.match(base, /MesloLGSNF-Regular\.woff2/, 'the mono face is a bundled file');
  assert.doesNotMatch(base, /url\(["']?https?:[^)]*\.ttf|url\(["']?https?:[^)]*\.woff/, 'faces are self-hosted, never fetched');
  assert.match(base, /font-variant-numeric:\s*tabular-nums/, 'data figures stay tabular');
  assert.doesNotMatch([statusbar, workspace, results].join('\n'), /system-ui/, 'visible shell and Results copy cannot fall back to a system face');
  assert.doesNotMatch(app, /wordmark-index|>01</, 'the product mark carries no unexplained instrument index');
  assert.match(statusbar, /\.wb-status\s*\{[^}]*height:\s*var\(--sb-h\)/s, 'the thin bar stays inside the 24-28px frame token');
  assert.match(inventory, /rv-files-kicker[^]*?t\('results\.kicker'\)/s);
  assert.match(inventory, /rv-files-title/);
  assert.match(layout, /WorkbenchPrompt[^]*?t\('results\.pickTitle'\)/s, 'the unselected Results canvas has a designed focal point');
});

test('every persistent desktop sidebar exposes one production resize handle', async () => {
  // Given: the shell, workspace Explorer, results inventory, and chat dock
  // sidebars. The workspace centre is a canvas; the Explorer owns the one
  // file list and resizes like the other sidebars.
  const [sidebar, explorer, resultsRail, dock, styles] = await Promise.all([
    read('../src/Sidebar.tsx'),
    read('../src/shell/ExplorerPanel.tsx'),
    read('../src/ResultsInventoryRail.tsx'),
    read('../src/shell/ChatDock.tsx'),
    read('../src/styles.css'),
  ]);

  // When: their interaction contracts are inspected.
  const persistentSidebars = [sidebar, explorer, resultsRail, dock];

  // Then: each uses the shared mouse-and-keyboard resize primitive.
  for (const source of persistentSidebars) assert.match(source, /PanelResizeHandle/);
  assert.match(styles, /resizable-panels\.css/);
});

test('the shared resize handle is accessible, bounded, and persistent', async () => {
  // Given: the shared sidebar resize primitive after implementation.
  const source = await read('../src/PanelResizeHandle.tsx');

  // When: pointer, keyboard, and persistence behavior are inspected.
  // Then: the handle exposes separator semantics and a durable bounded width.
  assert.match(source, /role="separator"/);
  assert.match(source, /aria-orientation="vertical"/);
  assert.match(source, /aria-valuemin=/);
  assert.match(source, /aria-valuemax=/);
  assert.match(source, /setPointerCapture/);
  assert.match(source, /writeLocalStorage/);
  assert.match(source, /ArrowLeft/);
  assert.match(source, /ArrowRight/);
  assert.match(source, /Home/);
  assert.match(source, /End/);
});

test('results supports multiple simultaneous plotted series with an explicit legend', async () => {
  // Given: the plot tab owns selection chips and the chart owns overlay paths.
  const [plot, chart] = await Promise.all([
    read('../src/ResultPlotTab.tsx'),
    read('../src/TrendChart.tsx'),
  ]);

  // When: selection and rendering paths are inspected.
  // Then: an ordered overlay collection reaches distinct chart paths and legend controls.
  assert.match(plot, /plottedSeries/);
  assert.match(plot, /aria-pressed=/);
  assert.match(plot, /overlay/);
  assert.match(chart, /overlays\.map/);
  assert.match(plot, /rv-chips/, 'one explicit legend names every plotted series');
  assert.match(plot, /t\('results\.overlays'\)/, 'the legend carries an accessible name');
});

test('results variables keep stable unique row identities', async () => {
  // The picker owns rows; the overlay owns selection: one domain key joins them.
  const [picker, overlay] = await Promise.all([
    read('../src/VariablePicker.tsx'),
    read('../src/useResultSeriesOverlay.ts'),
  ]);

  assert.doesNotMatch(picker, /<li key=\{v\.index\}>/, 'backend indices are not guaranteed unique across variable positions');
  assert.match(picker, /shown\.map\(\(v, index\) =>/);
  assert.match(picker, /key=\{`\$\{resultVariableKey\(v\)\}:\$\{index\}`\}/);
  assert.match(overlay, /const key = resultVariableKey\(variable\)/, 'overlay keys derive from the same domain key');
  assert.match(overlay, /item\.key === key/, 'row identity and overlay selection share one domain key');
});

test('mobile flowpath detail and run progress are directly revealed', async () => {
  // Given: topology selection, run presentation, and their responsive styles.
  const [topology, inspector, runOverview, runPanel, runStyles] = await Promise.all([
    read('../src/TopologyMap.tsx'),
    read('../src/TopologyInspector.tsx'),
    read('../src/RunViewOverview.tsx'),
    read('../src/RunSingleCasePanel.tsx'),
    read('../src/styles/run.css'),
  ]);

  // When: selected-detail and active-run paths are inspected.
  // Then: the flowpath opens beside the map (no replaced-map disclosure), and
  // neither feature depends on undisclosed horizontal or long vertical traversal.
  assert.match(topology, /TopologyInspector/);
  assert.match(topology, /flowpath-split/);
  assert.doesNotMatch(topology, /flowpath-studio-open/);
  assert.match(inspector, /FlowpathDetailPanel/);
  assert.match(runOverview, /<details className="run-alternatives"/);
  assert.match(runPanel, /run-progress-anchor/);
  assert.match(runStyles, /\.run-progress-anchor/);
});

test('export completion remains a visible live receipt', async () => {
  // Given: the Results export analysis surface.
  const source = await read('../src/ResultAnalysis.tsx');

  // When: completed figure and CSV branches render.
  // Then: assistive and visual users receive persistent ready-state feedback.
  assert.match(source, /className="result-export-receipts"/);
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /Figure export ready/);
  assert.match(source, /CSV export ready/);
});

test('the app shell never forces a desktop minimum width on mobile', async () => {
  // Given: Chrome can expose a content viewport narrower than the device width.
  const source = await read('../src/styles/base.css');

  // When: the global shell dimensions are inspected.
  // Then: body can shrink without creating a page-level horizontal scrollbar.
  assert.match(source, /body\s*\{[^}]*min-width:\s*0\b/s);
  assert.doesNotMatch(source, /body\s*\{[^}]*min-width:\s*360px\b/s);
});
