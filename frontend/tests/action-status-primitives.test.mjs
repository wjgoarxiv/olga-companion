import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readResultsSource } from './results-source.mjs';
import { readRunSource } from './run-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('Button exposes native props, three variants, exact busy copy, and accessible busy disabling', async () => {
  const button = await read('../src/ui/Button.tsx');

  assert.match(button, /ButtonHTMLAttributes<HTMLButtonElement>/);
  assert.match(button, /'primary'\s*\|\s*'secondary'\s*\|\s*'quiet'/);
  assert.match(button, /busyLabel/);
  assert.match(button, /aria-busy=\{busy\s*\|\|\s*undefined\}/);
  assert.match(button, /disabled=\{disabled\s*\|\|\s*busy\}/);
  assert.match(button, /busy\s*\?\s*busyLabel\s*\?\?/s, 'busy copy is explicit and falls back to the existing accessible name');
  assert.match(button, /className=\{\[.*ui-button.*className.*\]\.filter\(Boolean\)\.join\(' '\)\}/s);
  assert.match(button, /ui-button-label-measure/, 'the idle and busy labels reserve one stable action width');
  assert.doesNotMatch(button, /danger/);
});

test('OperationStatus maps neutral process states to status and errors to alerts', async () => {
  const status = await read('../src/ui/OperationStatus.tsx');

  assert.match(status, /'busy'\s*\|\s*'info'\s*\|\s*'success'\s*\|\s*'error'/);
  assert.match(status, /role=\{tone === 'error' \? 'alert' : 'status'\}/);
  assert.match(status, /title/);
  assert.match(status, /detail/);
  assert.match(status, /action/);
});

test('Receipt and Skeleton provide semantic evidence and accessible loading contracts', async () => {
  const [receipt, skeleton, css] = await Promise.all([
    read('../src/ui/Receipt.tsx'),
    read('../src/ui/Skeleton.tsx'),
    read('../src/styles/controls.css'),
  ]);

  assert.match(receipt, /aria-label=\{title\}/);
  assert.match(receipt, /receipt-title/);
  assert.match(receipt, /receipt-meta/);
  assert.match(receipt, /receipt-actions/);
  assert.match(skeleton, /<ActivityLoader[^>]*loadingLabel=\{loadingLabel\}/s, 'the shared loader owns the live-region semantics');
  assert.match(skeleton, /loadingLabel/);
  assert.match(skeleton, /visuallyHidden/);
  assert.match(css, /\.ui-skeleton/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.ui-skeleton[\s\S]*animation:\s*none/);
});

test('Results keeps figure and CSV exports on independent request epochs and visible states', async () => {
  const results = await readResultsSource(import.meta.url);

  for (const marker of [
    'figureExportRequestRef',
    'csvExportRequestRef',
    'figureExportLoading',
    'csvExportLoading',
    'figureExportError',
    'csvExportError',
  ]) assert.match(results, new RegExp(marker), marker);
  assert.match(results, /Creating figure…/);
  assert.match(results, /Creating CSV…/);
  assert.doesNotMatch(results, /const \[exportLoading/);
  assert.doesNotMatch(results, /const \[error[^\n]*export/i, 'export failures do not share one mutable error channel');
});

test('Run identifies six independent operations with exact action verbs', async () => {
  const run = await readRunSource();

  for (const marker of ['previewing', 'starting', 'cancelling', 'sweepPreviewing', 'sweepStarting', 'sweepCancelling']) {
    assert.match(run, new RegExp(`\\[${marker}, set${marker[0].toUpperCase()}${marker.slice(1)}\\]`), marker);
  }
  for (const [label, key] of [
    ['Preparing command…', 'run.opPreparing'],
    ['Starting OLGA…', 'run.opStarting'],
    ['Cancelling run…', 'run.opCancelling'],
    ['Preparing sweep…', 'run.opSweepPreview'],
    ['Starting sweep…', 'run.opSweepStarting'],
    ['Cancelling sweep…', 'run.(opSweepCancelling|sweepCancelling)'],
  ]) assert.match(run, new RegExp(`t\\('${key}'\\)`), label);
  assert.doesNotMatch(run, /const \[busy, setBusy\]/, 'polling/running is not a generic request flag');
  assert.match(run, /t\('run\.runtimeField'\)[\s\S]*disabled=\{safetyOperationActive\}/, 'runtime selection stays pinned during safety-critical operations');
  assert.match(run, /t\('sweep\.paramAria'\)[\s\S]*disabled=\{safetyOperationActive\}/, 'sweep inputs cannot invalidate an in-flight plan');
  assert.match(run, /\{sweepPreview \|\| sweepStatus \? \([\s\S]*<Receipt[\s\S]*<RunSweepStatus/, 'an accepted sweep preview is evidence, not a success placeholder');
});

test('high-value actions use the shared Button while list and navigation controls stay custom', async () => {
  const files = [
    'RuntimeNavStatus.tsx',
    'ChatView.tsx',
    'ApprovalCard.tsx',
    'MessageActions.tsx',
    'WorkspaceView.tsx',
    'ResultsView.tsx',
    'RunView.tsx',
    'RunFailurePanel.tsx',
    'SettingsView.tsx',
  ];
  const sources = await Promise.all(files.map((file) => (
    file === 'ResultsView.tsx'
      ? readResultsSource(import.meta.url)
      : file === 'RunView.tsx'
        ? readRunSource()
        : read(`../src/${file}`)
  )));

  files.filter((file) => file !== 'SettingsView.tsx').forEach((file) => {
    const index = files.indexOf(file);
    assert.match(sources[index], /import \{ Button \} from '\.\/ui\/Button'/, `${file} imports Button`);
    assert.match(sources[index], /<Button\b/, `${file} renders a high-value shared action`);
  });
  const [sidebar, calibration, results] = await Promise.all([
    read('../src/Sidebar.tsx'),
    read('../src/CalibrationRail.tsx'),
    readResultsSource(import.meta.url),
  ]);
  assert.match(sidebar, /<button\b/, 'navigation keeps its distinct affordance');
  assert.match(calibration, /<button\b/, 'segmented calibration controls stay distinct');
  assert.match(results, /<button[^>]*className=\{`ws-file/s, 'result rows stay selection controls');
  const settings = sources[files.indexOf('SettingsView.tsx')];
  assert.match(settings, /NativeContextActions/);
  assert.doesNotMatch(settings, /<Button\b/, 'Settings delegates workspace actions to the shared native action surface');
  assert.doesNotMatch(settings, /settingRoot|Setting workspace…/);
});

test('touched run and bootstrap status surfaces have no colored side stripe wider than a hairline', async () => {
  const [runCss, shellCss] = await Promise.all([
    read('../src/styles/run.css'),
    read('../src/styles/shell.css'),
  ]);
  const wideStripe = /border-(?:left|right):\s*(?:[2-9]|\d{2,})px\s+solid/;

  assert.doesNotMatch(runCss, wideStripe);
  assert.doesNotMatch(shellCss, wideStripe);
});
