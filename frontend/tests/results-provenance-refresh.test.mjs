import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readResultsSource } from './results-source.mjs';
import { readSessionSource } from './session-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('results refreshes inventory and opens the exact preferred result', async () => {
  const results = await readResultsSource(import.meta.url);
  const [app, centre] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/CentreViews.tsx'),
  ]);
  assert.match(results, /preferredResultId: string \| null/);
  assert.match(results, /async function refreshResults/);
  assert.match(results, /inventory\.results\.find\(\(result\) => result\.id === preferredResultId\)/);
  assert.match(results, />\{t\('results\.refresh'\)\}<\/Button>/);
  assert.match(results, /aria-label=\{t\('results\.refreshAria'\)\}/);
  assert.match(app, /preferredResultId/);
  assert.match(app, /function openResult\(resultId: string\)/);
  assert.match(app, /setPreferredResultId\(resultId\)[\s\S]*selectView\('results'\)/);
  assert.match(centre, /<ResultsView[\s\S]*preferredResultId=\{preferredResultId\}/);
  assert.match(centre, /<RunView[\s\S]*onOpenResult=\{onOpenResult\}/);
});

test('results inventory and variable loading copy remains honest', async () => {
  const results = await readResultsSource(import.meta.url);
  const api = await readSessionSource(import.meta.url);
  const css = await read('../src/styles/results.css');

  assert.match(results, /inventoryLoading/);
  assert.match(results, /variablesLoading/);
  assert.match(results, /t\(vars\.length === 1 \? 'results\.varOne' : 'results\.varOther', \{ count: vars\.length \}\)/);
  assert.match(results, /result\.run_state/);
  assert.match(results, /result\.lineage_status/);
  assert.match(api, /LINEAGE_STATUS_WIRE_FIELD = 'lineage_status'/, 'the frontend reads the field name the sidecar actually sends');
  assert.match(results, /result\.run_ok/);
  assert.match(css, /\.rv-main\.empty \.ui-skeleton\s*\{[^}]*grid-column:\s*1\s*\/\s*-1[^}]*width:\s*100%/s, 'the visible loading console spans the empty-state card instead of collapsing into one narrow grid column');
  assert.doesNotMatch(results, /title=\{(?:f|selected)\.(?:rel|path|source_sha256|output_sha256)\}/, 'absolute paths and hashes are not tooltips');
});

test('PPL plots a spatial profile while TPL graph and exact selected CSV export remain available', async () => {
  const api = await readSessionSource(import.meta.url);
  const results = await readResultsSource(import.meta.url);
  // The plot tab owns the chart; the export contract stays in the orchestrator.
  const plotTab = await read('../src/ResultPlotTab.tsx');

  assert.match(api, /exportSelectedCsv\([\s\S]*view\?: SeriesViewSpec/);
  assert.match(api, /body: JSON\.stringify\(\{ path, variables: \[variable\], position, \.\.\.\(view \? view : \{\}\) \}\)/);
  assert.match(results, /selected\.suffix === '\.ppl'/);
  // .ppl variables are selectable and render a spatial profile; only the
  // trend-driven exports stay tied to the .tpl overlay.
  assert.doesNotMatch(results, /disabled=\{selected\.suffix === '\.ppl'/);
  assert.match(results, /<ProfileControls[\s>]/);
  assert.match(plotTab, /TrendChart/, 'the plot tab renders the trend chart');
  assert.match(results, />\s*\{t\('analysis\.exportCsv'\)\}\s*<\/Button>/s);
  assert.match(results, /session\.exportSelectedCsv\(selected\.id, overlay\.activeVariable\.variable, overlay\.activeVariable\.position, overlay\.viewSpec\)/);
  assert.match(results, /csvExport\.row_count/);
  assert.match(results, /artifact=\{csvExport\.download_path\}/);
});

test('result inventory distinguishes receipt outputs from historical files honestly', async () => {
  const api = await readSessionSource(import.meta.url);
  const results = await readResultsSource(import.meta.url);

  for (const field of ['modified_ns', 'run_ok', 'runtime_kind', 'output_sha256']) {
    assert.match(api, new RegExp(`readonly ${field}`), `ResultFile types ${field}`);
  }
  assert.match(results, /function receiptBacked\(result: session\.ResultFile\)/);
  assert.match(results, /result\.lineage_status === 'receipt_output'/);
  assert.doesNotMatch(results, /result\.lineage\?\.kind === 'run_receipt'/);
  assert.match(results, /function resultStatusLabel\(result: session\.ResultFile\)/);
  assert.match(results, /'Completed'/);
  assert.match(results, /'Failed'/);
  assert.match(results, /'Partial'/);
  assert.match(results, /`Historical · Run \$\{runId\} · proven` \+ 'ance unavailable'/);
  assert.match(results, /modifiedLabel\(f\.modified_ns, locale\)/);
  assert.doesNotMatch(results, /\bFresh\b/i, 'unqualified historical files must not be called fresh');
  assert.doesNotMatch(results, /Workspace · \$\{f\.rel\}/, 'result context must not expose relative path chains');
});

test('historical results retain path-free run or workspace identity in list and selection', async () => {
  const results = await readResultsSource(import.meta.url);

  assert.match(results, /function resultContextLabel\(result: session\.ResultFile\): string/);
  assert.match(results, /result\.origin === 'run'/);
  assert.match(results, /result\.run_id \|\| result\.rel\.split\('\/'\)\[0\]/, 'legacy runs fall back to the first relative run segment');
  assert.match(results, /`Historical · Run \$\{runId\} · proven` \+ 'ance unavailable'/);
  assert.match(results, /`Workspace package result · \$\{result\.rel\}`/);
  assert.match(results, /resultContextLabel\(f\)/, 'inventory uses the identity label');
  assert.match(results, /resultContextLabel\(selected\)/, 'selected lineage uses the same identity label');
  assert.match(results, /historicalResultLabel\(runId\)/, 'historical copy is parameterized by run identity');
  assert.doesNotMatch(results, /const historicalResultLabel\s*=/, 'one generic legacy label cannot erase item identity');
});

test('preferred result handoff is consumed once so refresh retains current selection', async () => {
  const results = await readResultsSource(import.meta.url);
  const [app, centre] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/shell/CentreViews.tsx'),
  ]);
  assert.match(results, /onPreferredResultConsumed: \(\) => void/);
  assert.match(results, /await openFile\(exact\)[\s\S]*onPreferredResultConsumed\(\)/);
  assert.match(results, /useEffect\(\(\) => \{[\s\S]*refreshResults\(\)[\s\S]*\}, \[\]\)/);
  assert.match(app, /onPreferredResultConsumed=\{\(\) => setPreferredResultId\(null\)\}/);
});

test('CSV receipt preserves selected identity and offers artifact-only native Save As', async () => {
  const api = await readSessionSource(import.meta.url);
  const results = await readResultsSource(import.meta.url);

  for (const field of ['variable', 'position', 'unit', 'row_count', 'download_path']) {
    assert.match(api, new RegExp(`interface CsvExport[\\s\\S]*readonly ${field}:`), `CSV receipt keeps ${field}`);
  }
  assert.match(results, /csvExport\.variable/);
  assert.match(results, /csvExport\.position/);
  assert.match(results, /csvExport\.unit/);
  assert.match(results, /<NativeSaveAsAction[^>]*artifact=\{csvExport\.download_path\}/s);
  assert.doesNotMatch(results, /destination=|destination:/i);
});

test('result filtering and trend SVG expose accessible names with AA text colors', async () => {
  // One Explorer filter replaces two: the searchable variable picker carries
  // the input, with an accessible combobox name and 80-cap show-more.
  const layout = await read('../src/ResultsLayout.tsx');
  const picker = await read('../src/VariablePicker.tsx');
  const chart = await read('../src/TrendChart.tsx');
  const css = await read('../src/styles/results.css');

  assert.match(layout, /<ResultPlotTab/);
  assert.match(picker, /role="combobox"/);
  assert.match(picker, /t\('results\.pickVariables'\)/);
  assert.match(picker, /t\('results\.showMoreVars'/);
  // Crosshair readout keeps the accessible contract: status role, unit-bearing
  // i18n template, focusable SVG with named title/desc, AA text colors.
  assert.match(chart, /role="status"/);
  assert.match(chart, /t\('results\.readout'/);
  assert.match(chart, /tabIndex=\{0\}/);
  assert.match(chart, /aria-labelledby=\{/);
  assert.match(chart, /<title\b/);
  assert.match(chart, /<desc\b/);
  assert.match(css, /\.trend-readout\s*\{[^}]*color:\s*var\(--on-select\)[^}]*background:\s*var\(--select\)/s, 'readout text pairs with its own background in both themes');
  assert.match(css, /\.trend-tick\s*\{[^}]*fill:\s*var\(--mute\)/s);
  assert.match(css, /\.trend-pos\s*\{[^}]*color:\s*var\(--mute\)/s);
  assert.doesNotMatch(css, /\.trend-(?:tick|axis-label|pos|readout)\s*\{[^}]*var\(--stone\)/s);
});
