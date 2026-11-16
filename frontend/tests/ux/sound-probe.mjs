// Sound probe (lane lnsound): drives the app over CDP (agent-browser) and
// reads the test-only `window.__olgaSound()` hook that appearance.ts installs
// when `olga-companion.sound-debug.v1` is "1".
//
//   Phase 1, dev server:   the AudioContext is suspended before the first real
//                          gesture and running after it; a scripted view switch
//                          and a stubbed validation pass and fail leave the
//                          expected cue log.
//   Phase 2, built app:    the same bundle served with the production CSP header
//                          from src-tauri/tauri.conf.json raises no CSP violation.
//
// Read-only like pane-squeeze: the run-preview route is stubbed and only builds a
// command; /api/run/execute is never routed or clicked, no approval is clicked, no
// chat is sent. Invented demo names only.
//
//   PANE_SQUEEZE_PORT=5284 OLGA_SIDECAR_ORIGIN=http://127.0.0.1:8874 node --test frontend/tests/ux/sound-probe.mjs
import assert from 'node:assert/strict';
import test, { before, after } from 'node:test';
import { execFile } from 'node:child_process';
import { createServer as createHttpServer } from 'node:http';
import { mkdir, readFile } from 'node:fs/promises';
import { extname, resolve } from 'node:path';
import { promisify } from 'node:util';
import { createServer } from 'vite';

const exec = promisify(execFile);
const session = `olga-sound-probe-${process.pid}`;
const out = resolve(process.env.SOUND_PROBE_OUT || '/tmp/olga-sound-probe');
const port = Number(process.env.PANE_SQUEEZE_PORT || 0);
const DEMO_CASE = 'demo_sound_probe_line.genkey';

const browser = async (...args) =>
  (await exec('agent-browser', ['--session', session, ...args], { timeout: 45000 })).stdout.trim();
const evaluate = async (source) => {
  const result = JSON.parse(await browser('eval', `JSON.stringify(${source})`));
  return typeof result === 'string' ? JSON.parse(result) : result;
};
const route = async (path, body) => {
  await browser('network', 'unroute', `**${path}`).catch(() => undefined);
  return browser('network', 'route', `**${path}`, '--body', JSON.stringify(body));
};

const candidate = { candidate_id: 'demo-c1', runtime_id: 'demo-rt', exe: 'demo.exe', version: '2025.1', kind: 'opi', source: 'demo' };
const detection = {
  detected: true, source: 'demo', exe: 'demo.exe', kind: 'opi', searched: [], version: '2025.1',
  candidate_id: 'demo-c1', runtime_id: 'demo-rt', selection_status: 'selected', rationale: 'demo',
  required_version: null, candidates: [candidate], alternatives: [], evidence: [], case_source: DEMO_CASE,
};
const preview = (valid) => ({
  source: DEMO_CASE, selection_id: 'demo-sel', candidate_id: 'demo-c1', runtime_id: 'demo-rt', detection,
  display_command: ['demo.exe', DEMO_CASE], cwd_template: 'demo', timeout_s: 3600,
  validation: { valid, command: {} },
});

async function stubApp() {
  await route('/health', { app: 'OLGA Companion', version: '0.1.1', frontend_port: port, sidecar_port: 8874, capabilities: {} });
  await route('/api/session/token', { token: 'sound-probe-fixture-token' });
  await route('/api/providers', { providers: [{ provider: 'openai', known: true, has_catalog: true, models: [{ id: 'ui-fixture', label: 'UI fixture (not a live provider)' }] }] });
  await route('/api/llm-selection', { provider: 'openai', model: 'ui-fixture', variant: 'medium' });
  await route('/api/workspace/context', {
    root: '', generation: 1,
    cases: [{ name: DEMO_CASE, rel: DEMO_CASE, suffix: '.genkey', size: 4096, path: DEMO_CASE }],
    active: { name: DEMO_CASE, path: DEMO_CASE },
  });
  await route('/api/workspace/active', { name: DEMO_CASE, path: DEMO_CASE });
  await route('/api/workspace/list', { root: '', cases: [{ name: DEMO_CASE, rel: DEMO_CASE, suffix: '.genkey', size: 4096, path: DEMO_CASE }] });
  await route('/api/chat/session', { session_id: 'sound-probe-session' });
  await route('/api/chat/sessions', { sessions: [] });
  await route('/api/run/detect*', detection);
  await route('/api/run/history*', { runs: [] });
  await route('/api/run/preview', preview(true));
  await browser('network', 'route', '**/api/chat', '--abort');
}

async function freshLoad(url, { sound = 'full' } = {}) {
  await browser('open', url);
  await browser('wait', '#workbench-chat-dock');
  await evaluate(`(() => {
    localStorage.removeItem('olga-companion.workbench-layout.v1');
    localStorage.removeItem('olga_view');
    localStorage.setItem('olga-companion.sound.v1', '${sound}');
    localStorage.setItem('olga-companion.sound-volume.v1', '60');
    localStorage.setItem('olga-companion.sound-debug.v1', '1');
    localStorage.setItem('olga-companion.locale.v1', JSON.stringify({ version: 1, locale: 'en' }));
    return 'seeded';
  })()`);
  await browser('open', url);
  await browser('wait', '#workbench-chat-dock');
}

const soundState = () => evaluate(`(() => window.__olgaSound ? window.__olgaSound() : null)()`);

before(async () => {
  await mkdir(out, { recursive: true });
  await browser('open', 'about:blank');
  await browser('set', 'viewport', '1280', '800');
});

after(async () => {
  try { await browser('close', '--session'); } catch { /* session-scoped teardown */ }
});

test('dev server: the context is suspended before a gesture, running after one, and the cue log matches the script', async () => {
  const server = await createServer({
    configFile: 'frontend/vite.config.ts',
    server: { host: '127.0.0.1', port, strictPort: true },
    appType: 'spa',
  });
  await server.listen();
  try {
    await stubApp();
    await freshLoad(server.resolvedUrls.local[0]);

    const before = await soundState();
    assert.equal(before?.mode, 'full', 'the stored mode is applied at startup');
    assert.equal(before.state, 'suspended', 'no gesture yet: the autoplay policy keeps the context suspended');
    assert.deepEqual(before.cues, [], 'nothing sounded before any gesture');

    // One real pointer click (CDP input), then a scripted view switch.
    await browser('click', '.wb-activity [data-view="results"]');
    await browser('wait', '400');
    const after = await soundState();
    assert.equal(after.state, 'running', 'the first real gesture unlocks the context');
    assert.deepEqual(after.cues.map((entry) => entry.cue), ['tick'], 'one tick for the one view switch');

    // Stubbed validation: preview passes, then fails. The route only builds a command.
    const previewClick = `(() => { const b = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === 'Preview run'); b.click(); return !!b; })()`;
    assert.equal(await evaluate(previewClick), true);
    await browser('wait', '.run-view');
    await browser('wait', '1200');
    await route('/api/run/preview', preview(false));
    await evaluate(previewClick);
    await browser('wait', '1200');
    const log = (await soundState()).cues.map((entry) => entry.cue);
    await browser('screenshot', resolve(out, 'cue-log-run-view.png'));
    assert.deepEqual(log, ['tick', 'tick', 'pass', 'fail'], `cue log after view switch, run view, pass, fail: ${log.join(',')}`);
  } finally {
    await server.close();
  }
});

test('dev server: sound off builds no context and plays nothing', async () => {
  const server = await createServer({
    configFile: 'frontend/vite.config.ts',
    server: { host: '127.0.0.1', port, strictPort: true },
    appType: 'spa',
  });
  await server.listen();
  try {
    await stubApp();
    await freshLoad(server.resolvedUrls.local[0], { sound: 'off' });
    await browser('click', '.wb-activity [data-view="results"]');
    await browser('wait', '300');
    const state = await soundState();
    assert.equal(state.mode, 'off');
    assert.equal(state.state, 'none');
    assert.deepEqual(state.cues, []);
  } finally {
    await server.close();
  }
});

test('built app with the production CSP: the context unlocks and no violation is raised', async () => {
  const conf = JSON.parse(await readFile(resolve('src-tauri/tauri.conf.json'), 'utf8'));
  const csp = String(conf.app?.security?.csp ?? conf.tauri?.security?.csp ?? '');
  assert.match(csp, /default-src 'self'/, 'the production CSP is read from tauri.conf.json');
  const dist = resolve('frontend/dist');
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.json': 'application/json' };
  const probeScript = `window.__csp = []; document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));`;
  const server = createHttpServer(async (request, response) => {
    const path = new URL(request.url, 'http://x').pathname;
    if (path === '/csp-probe.js') {
      response.writeHead(200, { 'content-type': 'text/javascript', 'content-security-policy': csp });
      response.end(probeScript);
      return;
    }
    try {
      const file = path === '/' ? 'index.html' : path.slice(1);
      let body = await readFile(resolve(dist, file));
      if (file === 'index.html') body = Buffer.from(body.toString().replace('<head>', '<head><script src="/csp-probe.js"></script>'));
      response.writeHead(200, { 'content-type': types[extname(file)] ?? 'application/octet-stream', 'content-security-policy': csp });
      response.end(body);
    } catch {
      response.writeHead(404);
      response.end();
    }
  });
  await new Promise((done) => server.listen(port, '127.0.0.1', done));
  try {
    await stubApp();
    await freshLoad(`http://127.0.0.1:${port}/`);
    const before = await soundState();
    assert.equal(before?.state, 'suspended');
    await browser('click', '.wb-activity [data-view="results"]');
    await browser('wait', '400');
    const after = await soundState();
    assert.equal(after.state, 'running');
    assert.deepEqual(after.cues.map((entry) => entry.cue), ['tick']);
    const violations = await evaluate(`(() => window.__csp ?? 'probe-missing')()`);
    assert.deepEqual(violations, [], `CSP violations: ${JSON.stringify(violations)}`);
  } finally {
    await new Promise((done) => server.close(done));
  }
});
