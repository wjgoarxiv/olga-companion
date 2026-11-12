import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readRunSource } from './run-source.mjs';
import { readResultsSource } from './results-source.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('checkpoint 17: app exposes an operator-grade sidecar recovery path', async () => {
  const app = await read('../src/App.tsx');
  const status = await read('../src/RuntimeNavStatus.tsx');
  const css = await read('../src/styles/runtime-status.css');
  assert.match(app, /function bootstrap\(/, 'boot logic is retryable instead of one-shot inside useEffect');
  assert.match(app, /<StatusBar[\s\S]*?view=\{view\}[\s\S]*?state=\{runtime\.state\}/, 'sidecar status is mounted in the top-level navigation');
  assert.doesNotMatch(app, /className="boot-error"/, 'offline status no longer consumes content space');
  assert.match(status, /titleKey: 'runtime\.offlineTitle'/, 'offline state remains explicit without internal jargon');
  assert.match(status, /aria-label=\{t\('runtime\.retryAria'\)\}/, 'sidecar failure has an explicit recovery action');
  assert.match(status, /<Button[\s\S]*busyLabel=\{t\('runtime\.retrying'\)\}/, 'reconnect action names its exact busy operation');
  assert.match(css, /\.runtime-nav-status\s*\{[^}]*display:\s*grid/s, 'offline status is a bounded navigation cluster');
  assert.match(css, /@media \(max-width: 760px\)[^]*?\.runtime-nav-status-copy\s*\{[^}]*display:\s*grid/s, 'mobile navigation keeps the offline label and recovery action explicit');
});

test('checkpoint 17: Chat starters reflect the current workspace instead of demo sample copy', async () => {
  const app = await read('../src/App.tsx');
  const chat = await read('../src/ChatView.tsx');
  const empty = await read('../src/EmptyState.tsx');
  assert.match(app, /activeCaseName=\{activeCaseName\}/, 'Chat receives the active case name');
  assert.match(app, /workspaceCaseCount=\{workspaceCases\.length\}/, 'Chat receives workspace inventory size');
  assert.match(chat, /activeCaseName/, 'Chat passes active case context to EmptyState');
  assert.match(empty, /caseContext/, 'starters are built from current workspace context');
  assert.doesNotMatch(empty, /sample case/i, 'starter prompts must not imply bundled demo data is the active case');
});

test('checkpoint 17: Run sweep controls are structured before raw execution details', async () => {
  const run = await readRunSource();
  const builder = await read('../src/SweepValueBuilder.tsx');
  const css = await read('../src/styles/run.css');
  assert.match(run, /sweepParameter/, 'sweep parameter path is a first-class control');
  assert.match(run, /sweepValues/, 'sweep values are a first-class control');
  assert.match(run, /const sweepSpec =/, 'raw sweep spec is derived from structured controls');
  assert.match(run, /t\('sweep\.paramAria'\)/, 'parameter input is accessible');
  assert.match(builder, /aria-label=\{t\('sweep\.modeAria'\)\}/, 'value-building mode is accessible');
  assert.match(builder, /aria-label="Add sweep value"/, 'exact value entry is accessible');
  assert.doesNotMatch(run, /useState\('INTEGRATION\.ENDTIME=3600,7200'\)/, 'raw sweep expression is no longer the primary state');
  assert.match(css, /\.sweep-recipe\s*\{[^}]*display:\s*grid/s, 'structured sweep recipe has stable layout');
  assert.match(css, /\.sweep-value-mode\s*\{[^}]*grid-template-columns:/s, 'range and list modes remain visually explicit');
});

test('checkpoint 17: Results does not ship fast-follow copy as production UI', async () => {
  const results = await readResultsSource(import.meta.url);
  const plotTab = await read('../src/ResultPlotTab.tsx');
  assert.doesNotMatch(`${results}\n${plotTab}`, /fast-follow/i, 'production UI must not expose roadmap language');
  // .ppl review is no longer deferred: it plots a spatial profile, so the UI
  // must ship the real capability rather than copy explaining its absence.
  assert.doesNotMatch(`${results}\n${plotTab}`, /deferred|read-only in this view/i, 'production UI must not explain away a shipped capability');
  assert.match(plotTab, /<ProfilePanel[\s>]/, 'ppl results render their spatial profile');
});
