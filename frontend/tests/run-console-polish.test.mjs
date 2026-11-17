import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

const readCss = async () => {
  const root = await read('../src/styles.css');
  const imports = [...root.matchAll(/@import ['"](.+)['"];/g)];
  const imported = await Promise.all(imports.map((match) => read(`../src/${match[1]}`)));
  return [root, ...imported].join('\n');
};

test('run actions keep readable horizontal labels in constrained panels', async () => {
  // Given the shared button primitive and both Run action groups.
  const button = await read('../src/ui/Button.tsx');
  const single = await read('../src/RunSingleCasePanel.tsx');
  const sweep = await read('../src/RunSweepPanel.tsx');
  const css = await readCss();

  // When the cockpit is compressed to the annotated mid-desktop viewport.
  assert.match(single, /className="run-actions"/);
  assert.match(sweep, /className="sweep-actions"/);
  assert.match(button, /className="ui-button-label"/);

  // Then labels stay centered on one line and sweep actions own a stable row.
  assert.match(css, /\.ui-button-label\s*\{[^}]*white-space:\s*nowrap[^}]*overflow-wrap:\s*normal/s);
  assert.match(css, /\.run-action[s-][^\{]*\.ui-button-label\s*\{[^}]*width:\s*100%[^}]*place-items:\s*center[^}]*text-align:\s*center/s);
  assert.match(css, /\.run-actions\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/s);
  assert.match(css, /\.sweep-controls\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s);
  assert.match(css, /\.sweep-actions\s*\{[^}]*display:\s*grid[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/s);
});

test('single and sweep ride one Segmented control instead of a bespoke tablist', async () => {
  // Given the Run cockpit composition.
  const runView = await read('../src/RunView.tsx');
  const css = await readCss();

  // When an operator first opens Run.
  assert.match(runView, /useState<RunMode>\('single'\)/, 'single case is the default mode');
  assert.match(runView, /<Segmented/, 'Single/Sweep is the shared Segmented primitive');
  assert.match(runView, /ariaLabel=\{t\('run\.modeLabel'\)\}/);
  assert.match(runView, /label:\s*t\('run\.singleCase'\)/, 'single case option keeps its label');
  assert.match(runView, /label:\s*t\('run\.advancedSweep'\)/, 'sweep option keeps its label');
  assert.doesNotMatch(runView, /role="tablist" aria-label=\{t\('run\.modeLabel'\)\}/, 'no bespoke tablist for the mode switch');

  // Then only the selected workflow is mounted in the associated tab panel.
  assert.match(runView, /runMode === 'single' \? \([\s\S]*?<RunSingleCasePanel[\s\S]*?: \([\s\S]*?<RunSweepPanel/);
  assert.match(css, /\.run-mode \.ui-segmented-option\[aria-checked="true"\]\s*\{[^}]*box-shadow:\s*inset 0 0 0 1px var\(--accent\),\s*var\(--state-inset\)/s);
});

test('run typography and runtime evidence follow one editorial hierarchy', async () => {
  // Given the title and runtime-selection structure.
  const overview = await read('../src/RunViewOverview.tsx');
  const css = await readCss();

  // When the Run cockpit renders its heading and detection evidence.
  assert.match(overview, /className="run-title"/);
  assert.match(overview, /className="run-detection-evidence"/);

  // Then the heading inherits Pretendard and evidence is an aligned subordinate rail.
  assert.match(css, /\.run-title\s*\{[^}]*font-family:\s*inherit/s);
  assert.match(css, /\.run-detection-evidence\s*\{[^}]*border-left:\s*1px solid var\(--hairline-soft\)/s);
});

test('the detection grid stacks before its evidence rail can crush the summary', async () => {
  const css = await readCss();

  assert.match(
    css,
    /@container\s*\([^)]*max-width:\s*480px[^)]*\)[\s\S]*?\.run-detection\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s,
    'a narrow tab panel stacks the detection summary above the evidence',
  );
});

test('terminal result reads as an operational receipt instead of a loose status line', async () => {
  // Given terminal run evidence and its output inventory.
  const failure = await read('../src/RunFailurePanel.tsx');
  const css = await readCss();

  // When a run reaches a terminal state.
  assert.match(failure, /className={`run-terminal run-terminal-\$\{status\.state\}`}/);
  assert.match(failure, /className="run-terminal-state"/);
  assert.match(failure, /className="run-terminal-metric"/);
  assert.match(failure, /className="run-output-suffix"/);
  assert.match(failure, /<Table/, 'outputs ride the shared Table primitive');

  // Then state, metrics, and artifact types are visually separated and scan-ready.
  assert.match(css, /\.run-terminal\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\) auto/s);
  assert.match(css, /\.run-output-suffix\s*\{[^}]*text-transform:\s*uppercase/s);
  assert.match(css, /\.ui-table\s*\{[^}]*border-collapse:\s*collapse/s, 'the outputs table uses the primitive grid');
});

test('active case is prioritized over model chrome at mid-desktop widths', async () => {
  // Given a long engineering case name in the title-bar breadcrumb.
  const workspaceBar = await read('../src/WorkspaceBar.tsx');
  const shellTitle = await read('../src/shell/TitleBar.tsx');
  const statusCss = await read('../src/styles/statusbar.css');

  // When available width narrows, the crumb is the element that may shrink.
  assert.match(workspaceBar, /className="case-name-stem"/);
  assert.match(shellTitle, /className="wb-crumb"/, 'breadcrumb rides in the title bar');

  // Then lower-priority model text yields first: it truncates inside the
  // thin status bar while the breadcrumb keeps its bounded column.
  assert.match(statusCss, /\.wb-status-model\s*\{[^}]*min-width:\s*0;[^}]*text-overflow:\s*ellipsis/s);
});
