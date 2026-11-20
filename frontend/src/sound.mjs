/** Synthesized UI cues: oscillator, noise and waveshaper voices over one
    shared AudioContext. No audio files, no network, no dependencies.
    Short square and saw blips, noise ticks and a bit-crush stage give the
    neo-brutal sci-fi character; every cue is original and under 250 ms.
    Sound has its own setting and reads no other appearance choice. */

export const SOUND_MODES = ['off', 'quiet', 'full'];

/** Voice steps: osc = { wave, f: [from, to] Hz }, noise = { hp } high-pass Hz.
    `at` and `ms` are milliseconds from the cue start; `g` is the step peak. */
export const CUES = Object.freeze({
  tick: { tier: 'full', steps: [
    { v: 'osc', wave: 'square', f: [1800, 1200], at: 0, ms: 18, g: 0.5, crush: true },
    { v: 'noise', hp: 3000, at: 0, ms: 10, g: 0.3 },
  ] },
  grab: { tier: 'full', steps: [
    { v: 'osc', wave: 'sawtooth', f: [140, 220], at: 0, ms: 45, g: 0.6 },
    { v: 'noise', hp: 1500, at: 0, ms: 15, g: 0.25 },
  ] },
  release: { tier: 'full', steps: [
    { v: 'osc', wave: 'square', f: [260, 110], at: 0, ms: 55, g: 0.5, crush: true },
  ] },
  pass: { tier: 'quiet', steps: [
    { v: 'osc', wave: 'square', f: [660, 660], at: 0, ms: 70, g: 0.5 },
    { v: 'osc', wave: 'square', f: [990, 990], at: 80, ms: 100, g: 0.5 },
  ] },
  fail: { tier: 'quiet', steps: [
    { v: 'osc', wave: 'sawtooth', f: [240, 120], at: 0, ms: 90, g: 0.6, crush: true },
    { v: 'osc', wave: 'sawtooth', f: [180, 90], at: 100, ms: 110, g: 0.6, crush: true },
  ] },
  runDone: { tier: 'quiet', steps: [
    { v: 'osc', wave: 'square', f: [440, 440], at: 0, ms: 45, g: 0.45 },
    { v: 'osc', wave: 'square', f: [660, 660], at: 50, ms: 45, g: 0.45 },
    { v: 'osc', wave: 'square', f: [880, 880], at: 100, ms: 45, g: 0.45 },
    { v: 'osc', wave: 'square', f: [1320, 1320], at: 150, ms: 80, g: 0.45 },
  ] },
  runFail: { tier: 'quiet', steps: [
    { v: 'osc', wave: 'sawtooth', f: [330, 110], at: 0, ms: 160, g: 0.55, crush: true },
    { v: 'noise', hp: 800, at: 0, ms: 60, g: 0.3 },
    { v: 'osc', wave: 'square', f: [80, 80], at: 100, ms: 120, g: 0.5, crush: true },
  ] },
  done: { tier: 'quiet', steps: [
    { v: 'osc', wave: 'square', f: [520, 780], at: 0, ms: 60, g: 0.4 },
    { v: 'osc', wave: 'triangle', f: [1040, 1040], at: 70, ms: 90, g: 0.4 },
  ] },
  error: { tier: 'quiet', steps: [
    { v: 'noise', hp: 600, at: 0, ms: 40, g: 0.45 },
    { v: 'osc', wave: 'square', f: [150, 150], at: 0, ms: 80, g: 0.5, crush: true },
    { v: 'osc', wave: 'square', f: [120, 120], at: 100, ms: 100, g: 0.5, crush: true },
  ] },
});

export const DEFAULT_SOUND_VOLUME = 60;

export function parseSoundMode(value) {
  return SOUND_MODES.includes(value) ? value : null;
}

/** A stored volume is a whole number string from 0 to 100; anything else is unset. */
export function parseSoundVolume(value) {
  if (typeof value !== 'string' || !/^\d{1,3}$/.test(value)) return null;
  const volume = Number(value);
  return volume <= 100 ? volume : null;
}

const QUIET_LEVEL = 0.55;
const OUTPUT_CEILING = 0.5;
const LOG_LIMIT = 50;
const RUN_DONE_STATES = new Set(['completed']);
const RUN_FAIL_STATES = new Set(['failed', 'timed_out']);
const RUN_STOPPED_STATES = new Set(['cancelled']);

export function cueAllowed(mode, cue) {
  const def = CUES[cue];
  if (!def) return false;
  if (mode === 'full') return true;
  return mode === 'quiet' && def.tier === 'quiet';
}

export function cueDurationMs(cue) {
  const def = CUES[cue];
  return def ? Math.max(...def.steps.map((step) => step.at + step.ms)) : 0;
}

function clampVolume(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.min(100, Math.max(0, Math.round(number))) : 0;
}

function crushCurve() {
  const levels = 6;
  const curve = new Float32Array(257);
  for (let i = 0; i < curve.length; i += 1) {
    const x = (i / (curve.length - 1)) * 2 - 1;
    curve[i] = Math.round(x * levels) / levels;
  }
  return curve;
}

function documentHidden() {
  return typeof document !== 'undefined' && document.hidden === true;
}

export function createSound({ AudioContext: Ctor, isHidden = documentHidden, now = () => Date.now() } = {}) {
  let mode = 'off';
  let volume = 0;
  let ctx = null;
  let master = null;
  let noise = null;
  let crush = null;
  const tracked = new Set();
  const entries = [];

  const contextClass = () => Ctor ?? globalThis.AudioContext ?? globalThis.webkitAudioContext;

  function masterGain() {
    if (mode === 'off') return 0;
    return (volume / 100) * OUTPUT_CEILING * (mode === 'quiet' ? QUIET_LEVEL : 1);
  }

  function ensureContext() {
    if (ctx) return ctx;
    const Context = contextClass();
    if (typeof Context !== 'function') return null;
    try {
      ctx = new Context();
      master = ctx.createGain();
      master.connect(ctx.destination);
    } catch {
      ctx = null;
      master = null;
    }
    return ctx;
  }

  function applyMaster() {
    if (!ctx || !master) return;
    master.gain.setValueAtTime(masterGain(), ctx.currentTime);
  }

  function configure(next) {
    mode = SOUND_MODES.includes(next?.mode) ? next.mode : 'off';
    volume = clampVolume(next?.volume);
    if (mode !== 'off') ensureContext();
    applyMaster();
  }

  function unlock() {
    if (mode === 'off' || !ensureContext()) return;
    if (ctx.state === 'suspended') {
      try { Promise.resolve(ctx.resume()).catch(() => undefined); } catch { /* an unlock may retry on the next gesture */ }
    }
  }

  function noiseBuffer() {
    if (noise) return noise;
    const length = Math.max(1, Math.floor(ctx.sampleRate * 0.1));
    noise = ctx.createBuffer(1, length, ctx.sampleRate);
    const data = noise.getChannelData(0);
    for (let i = 0; i < length; i += 1) data[i] = Math.random() * 2 - 1;
    return noise;
  }

  function crusher() {
    if (crush) return crush;
    crush = ctx.createWaveShaper();
    crush.curve = crushCurve();
    crush.connect(master);
    return crush;
  }

  function schedule(def) {
    const t0 = ctx.currentTime + 0.005;
    for (const step of def.steps) {
      const start = t0 + step.at / 1000;
      const end = start + step.ms / 1000;
      const envelope = ctx.createGain();
      envelope.gain.setValueAtTime(0.0001, start);
      envelope.gain.linearRampToValueAtTime(step.g, start + 0.002);
      envelope.gain.exponentialRampToValueAtTime(0.0001, end);
      let source;
      if (step.v === 'noise') {
        source = ctx.createBufferSource();
        source.buffer = noiseBuffer();
        source.loop = true;
        const filter = ctx.createBiquadFilter();
        filter.type = 'highpass';
        filter.frequency.setValueAtTime(step.hp, start);
        source.connect(filter);
        filter.connect(envelope);
      } else {
        source = ctx.createOscillator();
        source.type = step.wave;
        source.frequency.setValueAtTime(step.f[0], start);
        if (step.f[1] !== step.f[0]) source.frequency.exponentialRampToValueAtTime(step.f[1], end);
        source.connect(envelope);
      }
      envelope.connect(step.crush ? crusher() : master);
      source.start(start);
      source.stop(end + 0.01);
    }
  }

  function emit(cue) {
    const def = CUES[cue];
    if (!def || masterGain() <= 0 || !ensureContext()) return false;
    // A context that is not running has a frozen clock; scheduling now would
    // replay this cue late, when it resumes. Drop it; the next gesture unlocks again.
    if (ctx.state !== 'running') return false;
    applyMaster();
    schedule(def);
    entries.push({ cue, at: now() });
    if (entries.length > LOG_LIMIT) entries.shift();
    return true;
  }

  function play(cue) {
    if (!cueAllowed(mode, cue) || isHidden()) return false;
    return emit(cue);
  }

  /** The Settings test button: a click, so it unlocks and plays one fixed cue. */
  function preview() {
    if (mode === 'off') return false;
    unlock();
    return emit('pass');
  }

  function trackRun(runId) {
    if (runId) tracked.add(runId);
  }

  /** Sounds the end of a run this session started, once. A run that was not
      tracked (history, restart recovery) never sounds. */
  function playRunOutcome(runId, state) {
    if (!tracked.has(runId)) return false;
    let cue = null;
    if (RUN_DONE_STATES.has(state)) cue = 'runDone';
    else if (RUN_FAIL_STATES.has(state)) cue = 'runFail';
    else if (!RUN_STOPPED_STATES.has(state)) return false;
    tracked.delete(runId);
    return cue ? play(cue) : false;
  }

  return {
    configure,
    unlock,
    play,
    preview,
    trackRun,
    playRunOutcome,
    masterGain,
    settings: () => ({ mode, volume }),
    audioState: () => (ctx ? ctx.state : 'none'),
    log: () => entries.slice(),
  };
}

const shared = createSound();

export const setSoundSettings = shared.configure;
export const unlockSound = shared.unlock;
export const playCue = shared.play;
export const previewCue = shared.preview;
export const trackRun = shared.trackRun;
export const cueRunOutcome = shared.playRunOutcome;

/** Unlocks the shared context on the first user gesture. With `debug`, a
    read-only `window.__olgaSound()` reports the context state and cue log
    for the test harness; it renders nothing. */
export function installSoundUnlock({ debug = false } = {}) {
  if (typeof window === 'undefined') return;
  const events = ['pointerdown', 'keydown'];
  // The listeners stay for the page's life: a context the browser suspends later
  // needs the next gesture to unlock it again. Unlocking a running context is a no-op.
  const onGesture = () => shared.unlock();
  for (const name of events) window.addEventListener(name, onGesture, true);
  if (debug) {
    window.__olgaSound = () => ({ ...shared.settings(), state: shared.audioState(), cues: shared.log() });
  }
}
