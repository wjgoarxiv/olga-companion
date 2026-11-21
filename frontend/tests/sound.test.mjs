import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const sound = await import('../src/sound.mjs');

/** A stub Web Audio graph: it records what was built, plays nothing. */
function stubAudio({ startState = 'running' } = {}) {
  const made = { contexts: [], oscillators: [], noises: [], gains: [], shapers: [], resumed: 0 };
  const param = () => ({
    value: 0,
    setValueAtTime(v) { this.value = v; return this; },
    linearRampToValueAtTime(v) { this.value = v; return this; },
    exponentialRampToValueAtTime(v) { this.value = v; return this; },
    cancelScheduledValues() { return this; },
  });
  const node = (extra = {}) => ({ connect(next) { return next; }, disconnect() {}, ...extra });
  class StubContext {
    constructor() {
      this.state = startState;
      this.currentTime = 0;
      this.sampleRate = 8000;
      this.destination = node({ kind: 'destination' });
      made.contexts.push(this);
    }
    resume() { made.resumed += 1; this.state = 'running'; return Promise.resolve(); }
    createGain() { const g = node({ kind: 'gain', gain: param() }); made.gains.push(g); return g; }
    createOscillator() {
      const o = node({ kind: 'osc', type: 'sine', frequency: param(), start() {}, stop() {} });
      made.oscillators.push(o);
      return o;
    }
    createBuffer(_channels, length) { return { getChannelData: () => new Float32Array(length) }; }
    createBufferSource() {
      const n = node({ kind: 'noise', buffer: null, start() {}, stop() {} });
      made.noises.push(n);
      return n;
    }
    createBiquadFilter() { return node({ kind: 'filter', type: 'lowpass', frequency: param(), Q: param() }); }
    createWaveShaper() { const s = node({ kind: 'shaper', curve: null }); made.shapers.push(s); return s; }
  }
  return { StubContext, made };
}

function engine({ hidden = false, startState } = {}) {
  const { StubContext, made } = stubAudio({ startState });
  const state = { hidden };
  const instance = sound.createSound({ AudioContext: StubContext, isHidden: () => state.hidden });
  return { instance, made, state };
}

const ALL_CUES = ['tick', 'grab', 'release', 'pass', 'fail', 'runDone', 'runFail', 'done', 'error'];
const QUIET_CUES = ['pass', 'fail', 'runDone', 'runFail', 'done', 'error'];

test('sound is off by default and builds no audio graph', () => {
  const { instance, made } = engine();
  assert.equal(instance.settings().mode, 'off');
  for (const cue of ALL_CUES) assert.equal(instance.play(cue), false, cue);
  assert.equal(made.contexts.length, 0);
  assert.deepEqual(instance.log(), []);
});

test('Quiet plays only the outcome cues and Full plays all of them', () => {
  assert.deepEqual(sound.SOUND_MODES, ['off', 'quiet', 'full']);
  for (const cue of ALL_CUES) {
    assert.equal(sound.cueAllowed('off', cue), false, `off ${cue}`);
    assert.equal(sound.cueAllowed('full', cue), true, `full ${cue}`);
    assert.equal(sound.cueAllowed('quiet', cue), QUIET_CUES.includes(cue), `quiet ${cue}`);
  }
  assert.equal(sound.cueAllowed('full', 'unknown-cue'), false);

  const { instance } = engine();
  instance.configure({ mode: 'quiet', volume: 80 });
  assert.deepEqual(ALL_CUES.filter((cue) => instance.play(cue)), QUIET_CUES);
  instance.configure({ mode: 'full', volume: 80 });
  assert.deepEqual(ALL_CUES.filter((cue) => instance.play(cue)), ALL_CUES);
});

test('every cue is under 250 ms and the cues sound different from each other', () => {
  const signatures = new Set();
  for (const cue of ALL_CUES) {
    const ms = sound.cueDurationMs(cue);
    assert.ok(ms > 0 && ms < 250, `${cue} lasts ${ms} ms`);
    signatures.add(JSON.stringify(sound.CUES[cue].steps));
  }
  assert.equal(signatures.size, ALL_CUES.length);
  // Outcome pairs must differ in more than loudness.
  for (const [a, b] of [['pass', 'fail'], ['runDone', 'runFail'], ['pass', 'runDone'], ['fail', 'runFail'], ['done', 'pass']]) {
    assert.notDeepEqual(sound.CUES[a].steps, sound.CUES[b].steps, `${a} vs ${b}`);
  }
});

test('the context is a singleton, created on demand and resumed on a gesture', () => {
  const { instance, made } = engine({ startState: 'suspended' });
  instance.configure({ mode: 'full', volume: 50 });
  assert.equal(made.contexts.length, 1);
  assert.equal(instance.audioState(), 'suspended');
  assert.equal(made.resumed, 0);
  instance.unlock();
  assert.equal(made.contexts.length, 1);
  assert.equal(made.resumed, 1);
  assert.equal(instance.audioState(), 'running');
  instance.play('tick');
  instance.play('pass');
  assert.equal(made.contexts.length, 1);
});

test('unlock builds no context while sound is off', () => {
  const { instance, made } = engine();
  instance.unlock();
  assert.equal(made.contexts.length, 0);
  assert.equal(instance.audioState(), 'none');
});

test('volume sets the master gain, and 0 plays nothing', () => {
  const { instance, made } = engine();
  instance.configure({ mode: 'full', volume: 100 });
  instance.play('pass');
  const loud = Math.max(...made.gains.map((g) => g.gain.value));
  assert.ok(loud > 0 && loud <= 1);
  const masterAt = (volume) => {
    const probe = engine();
    probe.instance.configure({ mode: 'full', volume });
    return probe.instance.masterGain();
  };
  assert.equal(masterAt(0), 0);
  assert.ok(masterAt(50) < masterAt(100));
  assert.ok(masterAt(100) <= 1);

  instance.configure({ mode: 'full', volume: 0 });
  assert.equal(instance.play('pass'), false);
});

test('Quiet is softer than Full at the same volume', () => {
  const quiet = engine();
  quiet.instance.configure({ mode: 'quiet', volume: 70 });
  const full = engine();
  full.instance.configure({ mode: 'full', volume: 70 });
  assert.ok(quiet.instance.masterGain() < full.instance.masterGain());
});

test('a hidden document gives no cue', () => {
  const { instance, state } = engine({ hidden: true });
  instance.configure({ mode: 'full', volume: 80 });
  assert.equal(instance.play('pass'), false);
  assert.equal(instance.playRunOutcome('r1', 'completed'), false);
  state.hidden = false;
  assert.equal(instance.play('pass'), true);
});

test('a run sounds once per run id, only when tracked, only when it ended', () => {
  const { instance } = engine();
  instance.configure({ mode: 'quiet', volume: 80 });
  // A run the user did not start in this session (restart recovery, history).
  assert.equal(instance.playRunOutcome('recovered', 'completed'), false);
  instance.trackRun('r1');
  assert.equal(instance.playRunOutcome('r1', 'running'), false, 'still running');
  assert.equal(instance.playRunOutcome('r1', 'completed'), true);
  assert.equal(instance.playRunOutcome('r1', 'completed'), false, 'once per run id');
  instance.trackRun('r2');
  assert.equal(instance.playRunOutcome('r2', 'failed'), true);
  instance.trackRun('r3');
  assert.equal(instance.playRunOutcome('r3', 'cancelled'), false, 'the user stopped it');
  assert.deepEqual(instance.log().map((entry) => entry.cue), ['runDone', 'runFail']);
});

test('a hidden window burns the run id without sounding, so a later poll cannot replay it', () => {
  const { instance, state } = engine({ hidden: true });
  instance.configure({ mode: 'quiet', volume: 80 });
  instance.trackRun('r1');
  assert.equal(instance.playRunOutcome('r1', 'completed'), false);
  state.hidden = false;
  assert.equal(instance.playRunOutcome('r1', 'completed'), false);
});

test('the test sound plays only when asked and only while sound is on', () => {
  const { instance, made } = engine();
  assert.equal(instance.preview(), false);
  instance.configure({ mode: 'full', volume: 40 });
  assert.equal(made.oscillators.length, 0, 'configuring plays nothing');
  assert.equal(instance.preview(), true);
  assert.ok(made.oscillators.length > 0);
});

test('the cue log records what sounded, for the test-only debug hook', () => {
  const { instance } = engine();
  instance.configure({ mode: 'full', volume: 60 });
  instance.play('tick');
  instance.play('pass');
  assert.deepEqual(instance.log().map((entry) => entry.cue), ['tick', 'pass']);
});

test('sound settings parse and default safely', () => {
  assert.equal(sound.parseSoundMode('quiet'), 'quiet');
  assert.equal(sound.parseSoundMode('loud'), null);
  assert.equal(sound.parseSoundMode(undefined), null);
  assert.equal(sound.parseSoundVolume('0'), 0);
  assert.equal(sound.parseSoundVolume('100'), 100);
  assert.equal(sound.parseSoundVolume('101'), null);
  assert.equal(sound.parseSoundVolume('-1'), null);
  assert.equal(sound.parseSoundVolume('abc'), null);
  assert.equal(sound.parseSoundVolume(''), null);
  assert.equal(sound.parseSoundVolume(null), null);
  assert.ok(sound.DEFAULT_SOUND_VOLUME > 0 && sound.DEFAULT_SOUND_VOLUME <= 100);
});

test('SoundChoice defaults to off and is stored through safeLocalStorage', async () => {
  const source = await read('../src/appearance.ts');
  assert.match(source, /export type SoundChoice = 'off' \| 'quiet' \| 'full';/);
  assert.match(source, /parseSound\(readLocalStorage\(SOUND_KEY\)\) \?\? 'off'/);
  assert.match(source, /writeLocalStorage\(SOUND_KEY, choice\)/);
  assert.match(source, /parseSoundVolume\(readLocalStorage\(SOUND_VOLUME_KEY\)\) \?\? DEFAULT_SOUND_VOLUME/);
  assert.match(source, /writeLocalStorage\(SOUND_VOLUME_KEY,/);
  assert.doesNotMatch(source, /\blocalStorage\.(?:getItem|setItem|removeItem)\b/);
  // initAppearance applies the stored choice before the first cue can fire.
  assert.match(source, /export function initAppearance\(\)[\s\S]*applySoundSettings\(\)[\s\S]*installSoundUnlock/);
});

test('the safety-critical and streaming paths import no sound', async () => {
  const guarded = [
    '../src/ApprovalCard.tsx',
    '../src/useApprovalContinuation.ts',
    '../src/useChatController.ts',
    '../src/sseClient.ts',
    '../src/ChatView.tsx',
    '../src/useChatActivity.ts',
    '../src/shell/caseProblems.ts',
    '../src/WorkspaceView.tsx',
    '../src/RunFailurePanel.tsx',
  ];
  for (const path of guarded) {
    const source = await read(path).catch(() => null);
    if (source === null) continue;
    assert.doesNotMatch(source, /from ['"][^'"]*\bsound(?:\.mjs)?['"]/, `${path} imports sound`);
    assert.doesNotMatch(source, /\b(?:playCue|previewCue|cueRunOutcome|trackRun)\s*\(/, `${path} plays a cue`);
  }
});

test('the chat stream cues only the settled outcome, never a delta', async () => {
  const source = await read('../src/useChatStream.ts');
  assert.match(source, /from ['"]\.\/sound\.mjs['"]/);
  const calls = [...source.matchAll(/playCue\(\s*['"]([a-zA-Z]+)['"]/g)].map((match) => match[1]);
  assert.ok(calls.length > 0 && calls.every((cue) => cue === 'done' || cue === 'error'), calls.join(','));
  // The per-event wrapper only records the outcome. It never plays.
  const wrapper = source.slice(source.indexOf('(event) =>'), source.indexOf('controller.signal,'));
  assert.doesNotMatch(wrapper, /playCue|sound/);
  // A turn that stopped for an approval is not a finished reply.
  assert.match(source, /approval_required/);
});

test('cues are wired only at their documented sources', async () => {
  const wired = {
    '../src/shell/useWorkbenchLayout.ts': /next !== viewRef\.current\) playCue\('tick'\)/,
    '../src/PanelResizeHandle.tsx': /playCue\(\s*'grab'[\s\S]*playCue\(\s*'release'/,
    '../src/shell/HeightResizer.tsx': /playCue\(\s*'grab'[\s\S]*playCue\(\s*'release'/,
    '../src/useRunActions.ts': /trackRun\(started\.run_id\)/,
  };
  for (const [path, pattern] of Object.entries(wired)) {
    assert.match(await read(path), pattern, path);
  }
  const lifecycle = await read('../src/useRunActions.ts');
  assert.match(lifecycle, /validation\.valid\s*\?\s*'pass'\s*:\s*'fail'/);
  // Restart recovery lives in the lifecycle hook: it may report an outcome but never arm a run.
  const lifecycleSource = await read('../src/useRunLifecycle.ts');
  assert.match(lifecycleSource, /cueRunOutcome\(next\.run_id, next\.state\)/);
  assert.doesNotMatch(lifecycleSource, /trackRun\(/);
});

test('the sound module needs no audio files, network or CSP change', async () => {
  const source = await read('../src/sound.mjs');
  assert.doesNotMatch(source, /new Audio\(|<audio|\.(?:mp3|wav|ogg)\b|fetch\(|decodeAudioData/);
  assert.doesNotMatch(source, /\bimport\b[^;]*from ['"](?!\.)/);
  const conf = await read('../../src-tauri/tauri.conf.json');
  assert.doesNotMatch(conf, /media-src/);
});

test('the sound setting is independent of the motion setting', async () => {
  const source = await read('../src/sound.mjs');
  assert.doesNotMatch(source, /motion|prefers-reduced/i);
});

test('Settings shows the Sound row, volume slider and test button in both locales', async () => {
  const view = await read('../src/SettingsView.tsx');
  assert.match(view, /id="display-sound-label"/);
  assert.match(view, /<SoundVolume\b/);
  const control = await read('../src/ui/SoundVolume.tsx');
  assert.match(control, /type="range"/);
  assert.match(control, /min=\{0\}\s+max=\{100\}/);
  assert.match(control, /onClick=\{\(\) => \{ previewCue\(\); \}\}/);
  assert.doesNotMatch(control, /onChange=\{[^}]*(?:previewCue|playCue)/, 'the slider is silent');
  const en = await read('../src/i18n/en.ts');
  const ko = await read('../src/i18n/ko.ts');
  for (const key of ['settings.sound', 'settings.soundOff', 'settings.soundQuiet', 'settings.soundFull', 'settings.soundVolume', 'settings.soundTest']) {
    assert.match(en, new RegExp(`'${key.replace('.', '\\.')}'`), `en ${key}`);
    assert.match(ko, new RegExp(`'${key.replace('.', '\\.')}'`), `ko ${key}`);
  }
});
