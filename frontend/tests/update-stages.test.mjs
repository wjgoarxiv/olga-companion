import assert from 'node:assert/strict';
import test from 'node:test';

// Lane B / T6: the update stage track is presentation only. The flow logic in
// updateInstall.mjs, updateAutoCheck.mjs and useLaunchUpdateCheck.ts is
// untouched; this test pins the presentational mapping plus the new markup.
const read = async (path) => (await import('node:fs/promises')).readFile(new URL(path, import.meta.url), 'utf8');

test('the stage track has six stages in order', async () => {
  const { UPDATE_STAGES } = await import('../src/updateStages.mjs');
  assert.deepEqual(UPDATE_STAGES, ['checking', 'available', 'downloading', 'verifying', 'installing', 'restarting']);
});

test('every panel phase maps to the track, including the error stage', async () => {
  const { stageOfPhase } = await import('../src/updateStages.mjs');
  const at = (kind, extra = {}) => stageOfPhase({ kind, ...extra }).states;
  assert.deepEqual(at('idle'), { checking: 'todo', available: 'todo', downloading: 'todo', verifying: 'todo', installing: 'todo', restarting: 'todo' });
  assert.equal(stageOfPhase({ kind: 'checking' }).active, 'checking');
  assert.equal(at('checking').checking, 'active');
  assert.deepEqual(at('current'), { checking: 'done', available: 'todo', downloading: 'todo', verifying: 'todo', installing: 'todo', restarting: 'todo' });
  assert.equal(stageOfPhase({ kind: 'available' }).active, 'available');
  assert.equal(stageOfPhase({ kind: 'downloading' }).active, 'downloading');
  const downloaded = stageOfPhase({ kind: 'downloaded' });
  assert.equal(downloaded.active, null, 'after download the signature is verified and the track waits for install');
  for (const id of ['checking', 'available', 'downloading', 'verifying']) assert.equal(downloaded.states[id], 'done');
  assert.equal(stageOfPhase({ kind: 'installing' }).active, 'installing');
  const blocked = stageOfPhase({ kind: 'blocked' });
  assert.equal(blocked.blocked, 'installing', 'a refusal blocks at the install step and keeps it retryable');
  assert.equal(blocked.states.installing, 'blocked');
  assert.equal(stageOfPhase({ kind: 'error', stage: 'downloading', backendStopped: false }).failed, 'downloading');
  assert.equal(stageOfPhase({ kind: 'error', stage: 'checking', backendStopped: false }).failed, 'checking');
  assert.equal(stageOfPhase({ kind: 'error', stage: 'installing', backendStopped: true }).failed, 'installing');
  const failed = stageOfPhase({ kind: 'error', stage: 'downloading', backendStopped: false });
  assert.equal(failed.states.downloading, 'failed');
  assert.equal(failed.states.checking, 'done', 'stages before the failure stay done');
  assert.equal(failed.states.verifying, 'todo', 'stages after the failure stay todo');
  assert.deepEqual(at('unsupported'), { checking: 'todo', available: 'todo', downloading: 'todo', verifying: 'todo', installing: 'todo', restarting: 'todo' });
});

test('UpdatePanel renders the stage track, a progress ring, RollingNumber figures and expandable notes', async () => {
  const panel = await read('../src/UpdatePanel.tsx');
  assert.match(panel, /from '.\/updateStages\.mjs'/, 'the panel maps phases through the stage module');
  assert.match(panel, /<ol className="update-stages" aria-label=\{t\('update\.stagesAria'\)\}>/, 'the track is a labelled list');
  assert.match(panel, /aria-current=\{track\.active === id \? 'step' : undefined\}/, 'the active stage is exposed to assistive tech');
  assert.match(panel, /<svg[^>]*className="update-ring"/, 'a progress ring sits next to the bar');
  assert.match(panel, /<RollingNumber/, 'MB and MB/s roll instead of jumping');
  assert.match(panel, /MB\/s/, 'the rate still reads MB/s');
  for (const stage of ['checking', 'available', 'downloading', 'verifying', 'installing', 'restarting']) {
    assert.match(panel, new RegExp(`t\\('update\\.stage\\.${stage}'\\)`), `the ${stage} stage label is translated`);
  }
  assert.match(panel, /className="update-version-reveal"/, 'the new version number gets a reveal');
  assert.match(panel, /t\('update\.showNotes'\)/, 'expanding the notes is translated');
  assert.match(panel, /t\('update\.hideNotes'\)/, 'collapsing the notes is translated');
  assert.match(panel, /aria-expanded=\{/, 'the notes toggle exposes its state');
  assert.match(panel, /installUpdate\(/, 'the Install button still routes through the guarded flow');
});

test('UpdateNotice reveals the new version and keeps its wiring', async () => {
  const notice = await read('../src/UpdateNotice.tsx');
  assert.match(notice, /update-notice-reveal/, 'the notice version gets a reveal');
  assert.match(notice, /requestOpenUpdates\(\)/, 'opening still routes to Settings → Updates');
  assert.match(notice, /<div className="update-notice-live" role="status" aria-live="polite">/, 'the live region stays mounted');
  assert.doesNotMatch(notice, /\.download\(|\.install\(|downloadAndInstall|plugin-updater/, 'the notice still downloads and installs nothing');
});

test('the new update strings exist in both languages', async () => {
  const [en, ko] = await Promise.all([read('../src/i18n/en.ts'), read('../src/i18n/ko.ts')]);
  for (const key of ['update.stage.checking', 'update.stage.available', 'update.stage.downloading',
    'update.stage.verifying', 'update.stage.installing', 'update.stage.restarting',
    'update.stagesAria', 'update.showNotes', 'update.hideNotes']) {
    assert.match(en, new RegExp(`'${key.replace(/\./g, '\\.')}':`), `en ${key}`);
    assert.match(ko, new RegExp(`'${key.replace(/\./g, '\\.')}':`), `ko ${key}`);
  }
});
