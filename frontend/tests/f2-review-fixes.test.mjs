import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

// ai-dock-and-neo-fx F2 review: m7 server text, m9 draft cap, m10 late sound replay.

test('m7: a transition error shows the server message when the body has no detail', async () => {
  const api = await read('../src/chatSessionApi.ts');
  assert.match(api, /record\.detail/);
  assert.match(api, /typeof record\.message === 'string'/, 'an uncertain 409 carries `message`, not `detail`');
});

test('m9: the draft reducer never accumulates past the cap and keeps the newest text', async () => {
  const { reduceDraft, DRAFT_LIMIT } = await import('../src/chatDraft.mjs');
  let draft = '';
  for (let i = 0; i < 40; i += 1) draft = reduceDraft(draft, { type: 'draft', data: { text: `${'x'.repeat(DRAFT_LIMIT / 4)}#${i}` } });
  assert.ok(draft.length <= DRAFT_LIMIT, `draft held ${draft.length} characters`);
  assert.ok(draft.endsWith('#39'), 'the tail is the newest text');
});

function stubAudio({ startState }) {
  const made = { oscillators: 0, resumed: 0, ctx: null };
  const param = () => ({ setValueAtTime() { return this; }, linearRampToValueAtTime() { return this; }, exponentialRampToValueAtTime() { return this; } });
  const node = (extra = {}) => ({ connect(next) { return next; }, ...extra });
  class StubContext {
    constructor() {
      this.state = startState;
      this.currentTime = 0;
      this.sampleRate = 8000;
      this.destination = node();
      made.ctx = this;
    }
    resume() { made.resumed += 1; return Promise.resolve(); }
    createGain() { return node({ gain: param() }); }
    createOscillator() { made.oscillators += 1; return node({ frequency: param(), start() {}, stop() {} }); }
    createBuffer(_c, length) { return { getChannelData: () => new Float32Array(length) }; }
    createBufferSource() { return node({ start() {}, stop() {} }); }
    createBiquadFilter() { return node({ frequency: param() }); }
    createWaveShaper() { return node(); }
  }
  return { StubContext, made };
}

test('m10: a cue is dropped, not replayed late, while the context is not running', async () => {
  const sound = await import('../src/sound.mjs');
  const { StubContext, made } = stubAudio({ startState: 'suspended' });
  const instance = sound.createSound({ AudioContext: StubContext, isHidden: () => false });
  instance.configure({ mode: 'full', volume: 60 });
  instance.unlock(); // the gesture asked for a resume that has not settled yet
  assert.equal(instance.play('pass'), false, 'suspended at cue time: dropped');
  assert.equal(made.oscillators, 0, 'nothing was scheduled on the frozen clock');
  assert.deepEqual(instance.log(), []);

  made.ctx.state = 'running';
  assert.equal(instance.play('pass'), true, 'once running, cues play on time');
  assert.ok(made.oscillators > 0);

  made.ctx.state = 'suspended'; // the browser interrupted the context later
  const before = made.oscillators;
  assert.equal(instance.play('pass'), false);
  assert.equal(made.oscillators, before, 'a later suspension drops the cue too');
  const resumes = made.resumed;
  instance.unlock();
  assert.equal(made.resumed, resumes + 1, 'the next gesture asks for a resume again');
});

test('m10: the gesture listeners stay armed so a later suspension can unlock again', async () => {
  const listeners = new Map();
  const removed = [];
  globalThis.window = {
    addEventListener: (name, fn) => listeners.set(name, fn),
    removeEventListener: (name) => removed.push(name),
  };
  const { StubContext, made } = stubAudio({ startState: 'suspended' });
  globalThis.AudioContext = StubContext;
  try {
    const sound = await import('../src/sound.mjs');
    sound.setSoundSettings({ mode: 'full', volume: 50 });
    sound.installSoundUnlock();
    made.ctx.resume = () => { made.resumed += 1; made.ctx.state = 'running'; return Promise.resolve(); };
    listeners.get('pointerdown')();
    assert.equal(made.ctx.state, 'running');
    assert.deepEqual(removed, [], 'listeners are not removed once running');
  } finally {
    delete globalThis.window;
    delete globalThis.AudioContext;
  }
});
