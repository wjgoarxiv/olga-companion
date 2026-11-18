import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { ko } from '../src/i18n/ko.ts';
import { en } from '../src/i18n/en.ts';
import { translate } from '../src/i18n/index.ts';

const { deriveStepStates, deriveStatusLine } = await import('../src/shell/useStepState.ts');
const live = await import('../src/shell/liveStatus.ts');

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const running = (id, fraction) => ({
  kind: 'run',
  status: { run_id: id, state: 'running', solver_progress: fraction == null ? undefined : { fraction, vendor_percent: fraction * 100 } },
});
const done = (id, state) => ({ kind: 'run', status: { run_id: id, state } });
const states = (over) => deriveStepStates({
  activeCaseName: 'net.genkey', tabCount: 1, hasRunOutputs: false, errorCount: 0,
  hasEvidence: true, preferredResultId: null, ...over,
});

test('the title bar shows the same status line the step bar derives', async () => {
  const [title, bar] = await Promise.all([read('../src/shell/TitleBar.tsx'), read('../src/shell/StepBar.tsx')]);
  assert.match(bar, /publishStatusLine\(/, 'the step bar publishes the line it derived');
  assert.match(title, /useLiveStatus\(\)/);
  assert.match(title, /className="wb-statusline"/);
  assert.match(title, /statusLineText\(/);
  assert.doesNotMatch(title, /onApprove|executeApproval|sendMessage/, 'the status never approves or sends');
});

test('publishing a status line reaches subscribers and reset clears it', () => {
  live.resetLiveStatus();
  let calls = 0;
  const stop = live.subscribeLiveStatus(() => { calls += 1; });
  live.publishStatusLine({ key: 'stepbar.line.saved', params: { case: 'net.genkey' } }, 'validate');
  assert.deepEqual(live.getLiveStatus().statusLine, { key: 'stepbar.line.saved', params: { case: 'net.genkey' } });
  assert.equal(live.getLiveStatus().nextKind, 'validate');
  assert.equal(calls, 1);
  live.publishStatusLine({ key: 'stepbar.line.saved', params: { case: 'net.genkey' } }, 'validate');
  assert.equal(calls, 1, 'an identical line does not notify again');
  stop();
  live.resetLiveStatus();
  assert.equal(live.getLiveStatus().statusLine, null);
});

test('the running line carries the live percent and says it can be cancelled', () => {
  const withPct = deriveStatusLine({ states: states({ runInFlight: true }), timeline: [], activeCaseName: 'net.genkey', runPercent: 42 });
  assert.deepEqual(withPct, { key: 'stepbar.line.runningPct', params: { case: 'net.genkey', percent: 42 } });
  const without = deriveStatusLine({ states: states({ runInFlight: true }), timeline: [], activeCaseName: 'net.genkey', runPercent: null });
  assert.equal(without.key, 'stepbar.line.running', 'unknown progress keeps the plain running line');
  assert.equal(deriveStatusLine({ states: states({}), timeline: [], activeCaseName: 'net.genkey', runPercent: 42 }).key, 'stepbar.line.checked', 'a percent never changes a non-running line');
  assert.match(translate('ko', 'stepbar.line.runningPct', { case: 'net.genkey', percent: 42 }), /실행 중 42% · 취소 가능/);
  assert.match(translate('en', 'stepbar.line.runningPct', { case: 'net.genkey', percent: 42 }), /running 42% · can be cancelled/);
  assert.notEqual(ko['stepbar.line.runningPct'], en['stepbar.line.runningPct']);
});

test('run observations give a percent only while the run is live', () => {
  live.resetLiveStatus();
  live.ingestRunObservation(running('r1', 0.42));
  assert.equal(live.getLiveStatus().runPercent, 42);
  live.ingestRunObservation(running('r1', 0.5));
  assert.equal(live.getLiveStatus().runPercent, 50);
  live.ingestRunObservation(running('r1', undefined));
  assert.equal(live.getLiveStatus().runPercent, null, 'a run with no known percent is indeterminate');
  assert.equal(live.getLiveStatus().runLive, true);
  live.ingestRunObservation(done('r1', 'completed'));
  assert.equal(live.getLiveStatus().runPercent, null);
  assert.equal(live.getLiveStatus().runLive, false);
  live.ingestRunObservation({ kind: 'sweep', status: { sweep_id: 's', state: 'running', cases: [] } });
  assert.equal(live.getLiveStatus().runLive, false, 'a sweep is not a run');
  live.resetLiveStatus();
});

test('the status line text formats the approval action and the percent', () => {
  const t = (key, vars) => translate('ko', key, vars);
  assert.match(live.statusLineText(t, { key: 'stepbar.line.approval', params: { action: 'run' } }), /승인 대기: 실행/);
  assert.match(live.statusLineText(t, { key: 'stepbar.line.runningPct', params: { case: 'a.genkey', percent: 7 } }), /a\.genkey 실행 중 7%/);
  assert.equal(live.statusLineTone('stepbar.line.approval'), 'wait');
  assert.equal(live.statusLineTone('stepbar.line.errors'), 'blocked');
  assert.equal(live.statusLineTone('stepbar.line.runningPct'), 'live');
  assert.equal(live.statusLineTone('stepbar.line.saved'), 'plain');
});

test('tab badges: running shows while live, new result and error clear when the tab is visited', () => {
  live.resetLiveStatus();
  assert.deepEqual(live.deriveTabBadges(live.getLiveStatus(), 'workspace'), {});
  live.ingestRunObservation(running('r1', 0.1));
  assert.deepEqual(live.deriveTabBadges(live.getLiveStatus(), 'workspace'), { run: 'running' });
  live.ingestRunObservation(done('r1', 'completed'));
  assert.deepEqual(live.deriveTabBadges(live.getLiveStatus(), 'workspace'), { results: 'newResult' });
  assert.deepEqual(live.deriveTabBadges(live.getLiveStatus(), 'results'), {}, 'looking at results clears it');
  live.acknowledgeView('results');
  assert.deepEqual(live.deriveTabBadges(live.getLiveStatus(), 'workspace'), {}, 'and it stays cleared');
  live.ingestRunObservation(running('r2', 0.3));
  live.ingestRunObservation(done('r2', 'failed'));
  assert.deepEqual(live.deriveTabBadges(live.getLiveStatus(), 'workspace'), { run: 'error' });
  live.acknowledgeView('run');
  assert.deepEqual(live.deriveTabBadges(live.getLiveStatus(), 'workspace'), {});
  live.resetLiveStatus();
});

test('a finished run first seen already finished, or a cancelled run, leaves no badge', () => {
  live.resetLiveStatus();
  live.ingestRunObservation(done('old', 'completed'));
  assert.deepEqual(live.deriveTabBadges(live.getLiveStatus(), 'workspace'), {}, 'a restored record is not new');
  live.ingestRunObservation(running('r3', 0.2));
  live.ingestRunObservation(done('r3', 'cancelled'));
  assert.deepEqual(live.deriveTabBadges(live.getLiveStatus(), 'workspace'), {}, 'the user asked for the stop');
  live.resetLiveStatus();
});

test('a new run replaces an unseen error badge with running', () => {
  live.resetLiveStatus();
  live.ingestRunObservation(running('r1', 0.2));
  live.ingestRunObservation(done('r1', 'timed_out'));
  assert.deepEqual(live.deriveTabBadges(live.getLiveStatus(), 'workspace'), { run: 'error' });
  live.ingestRunObservation(running('r2', 0.2));
  assert.deepEqual(live.deriveTabBadges(live.getLiveStatus(), 'workspace'), { run: 'running' });
  live.resetLiveStatus();
});

test('the centre tab strip renders the badges and acknowledges the visited tab', async () => {
  const [centre, tabs] = await Promise.all([read('../src/shell/CentreViews.tsx'), read('../src/ui/Tabs.tsx')]);
  assert.match(centre, /deriveTabBadges\(/);
  assert.match(centre, /acknowledgeView\(view\)/);
  assert.match(centre, /badgeKind/);
  assert.match(tabs, /data-kind=\{item\.badgeKind\}/);
  for (const key of ['tab.badge.running', 'tab.badge.newResult', 'tab.badge.error']) {
    assert.ok(ko[key] && en[key], key);
    assert.notEqual(ko[key], en[key], `${key} ko differs from en`);
  }
});

test('exactly one title-bar action carries the emphasis, the one the step bar points at', () => {
  assert.equal(live.titleBarPrimary('validate', false), 'validate');
  assert.equal(live.titleBarPrimary('preview-run', false), 'preview');
  for (const kind of ['open-run', 'open-results', 'edit', 'new-case', 'none', null, undefined]) {
    assert.equal(live.titleBarPrimary(kind, false), 'run', String(kind));
  }
  assert.equal(live.titleBarPrimary('validate', true), 'run', 'a busy run keeps its progress fill');
});

test('the title bar applies the emphasis to one button and styles the new parts with tokens', async () => {
  const [title, wb, guide] = await Promise.all([
    read('../src/shell/TitleBar.tsx'), read('../src/styles/workbench.css'), read('../src/styles/simulation-guide.css'),
  ]);
  assert.match(title, /titleBarPrimary\(/);
  assert.equal((title.match(/primary === '(validate|preview|run)' \? ' wb-btn-primary'/g) ?? []).length, 3);
  const css = `${wb}\n${guide}`;
  for (const rule of ['.wb-statusline', '.ui-tab-badge[data-kind']) {
    assert.ok(css.includes(rule), rule);
  }
  const added = css.match(/\.wb-statusline[^{]*\{[^}]*\}|\.ui-tab-badge\[data-kind[^{]*\{[^}]*\}/g).join('\n');
  assert.doesNotMatch(added, /#[0-9a-fA-F]{3,8}\b|border-radius:\s*[1-9]|font-size:\s*\d+px|infinite/);
});
