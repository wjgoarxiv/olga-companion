// Drives the real UpdatePanel in the built app through Check -> Download -> Install while
// the native `stop_sidecar` command refuses. Everything Tauri provides (updater plugin,
// invoke, process plugin) is replaced by an explicit in-page fixture, so this is evidence
// about the component's screens and behaviour, not about a real updater, signature,
// installer or the owner's installed app: no network update channel is contacted and the
// fixture's `install` and `restart` must stay at zero calls in every refusal scenario.
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { promisify } from 'node:util';
import { preview } from 'vite';

const exec = promisify(execFile);
const session = `olga-update-panel-${process.pid}`;
const out = resolve(process.argv[2] || '/tmp/opencode/olga-update-panel-browser');
const browser = async (...args) => (await exec('agent-browser', ['--session', session, ...args], { timeout: 30000 })).stdout.trim();
const evaluate = async (source) => {
  const result = JSON.parse(await browser('eval', `JSON.stringify(${source})`));
  return typeof result === 'string' ? JSON.parse(result) : result;
};
const route = async (path, body) => {
  await browser('network', 'unroute', `**${path}`);
  return browser('network', 'route', `**${path}`, '--body', JSON.stringify(body));
};

const MESSAGES = {
  run_active: 'Installing the update stops the local backend and would end work in progress: run(s) still active or with unknown status: fixture-run (running). Open Run, wait for them to finish or cancel them, then install again.',
  unconfirmed: 'Could not confirm that no run is active, so the update was not installed. Open Run to check on your runs, then try again.',
  stop_failed: 'The local backend did not stop, so the update was not installed. Close OLGA Companion from the Task Manager (olga-companion-sidecar.exe) and open it again.',
};

const fixture = `(() => {
  const callbacks = new Map();
  let nextId = 1;
  window.__tauriCalls = [];
  window.__stopMode = 'ok';
  window.__installMode = 'ok';
  window.__TAURI_INTERNALS__ = {
    transformCallback(callback) { const id = nextId++; callbacks.set(id, callback); return id; },
    unregisterCallback(id) { callbacks.delete(id); },
    convertFileSrc: (path) => path,
    async invoke(command, args) {
      window.__tauriCalls.push(command);
      if (command === 'plugin:updater|check') return { rid: 11, currentVersion: '0.1.1', version: '0.2.0', date: '2030-01-01T00:00:00Z', body: 'Fixture release notes. Not a real release.' };
      if (command === 'plugin:updater|download') {
        const send = callbacks.get(args.onEvent.id);
        send({ index: 0, message: { event: 'Started', data: { contentLength: 4000000 } } });
        send({ index: 1, message: { event: 'Progress', data: { chunkLength: 4000000 } } });
        send({ index: 2, message: { event: 'Finished' } });
        return 12;
      }
      if (command === 'plugin:updater|install') {
        if (window.__installMode === 'fail') throw new Error('fixture installer failed');
        return null;
      }
      if (command === 'plugin:process|restart') return null;
      if (command === 'plugin:resources|close') return null;
      if (command === 'stop_sidecar') {
        const mode = window.__stopMode;
        if (mode === 'ok') return null;
        if (mode === 'plain') throw new Error('fixture: command stop_sidecar not found');
        throw { code: mode, message: window.__messages[mode] };
      }
      throw new Error('unexpected tauri command in fixture: ' + command);
    },
  };
})()`;

const until = async (predicate, what) => {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    if (await evaluate(predicate)) return;
    await new Promise((done) => setTimeout(done, 50));
  }
  assert.fail(`timed out waiting for ${what}`);
};
const calls = () => evaluate('window.__tauriCalls');
const count = async (command) => (await calls()).filter((name) => name === command).length;
const status = () => evaluate('document.querySelector(".update-status").textContent.trim()');
const actions = () => evaluate('[...document.querySelectorAll(".update-actions button")].map((button) => button.textContent.trim())');

const server = await preview({ configFile: 'frontend/vite.config.ts', preview: { host: '127.0.0.1', port: 0, strictPort: true } });
try {
  await mkdir(out, { recursive: true });
  await browser('open', 'about:blank');
  await route('/health', { app: 'OLGA Companion', version: '0.1.1', frontend_port: 5273, sidecar_port: 8865, capabilities: {} });
  await route('/api/session/token', { token: 'isolated-ui-fixture-token' });
  await route('/api/providers', { providers: [] });
  await route('/api/workspace/context', { root: '', cases: [], active: { name: null, path: null }, generation: 0 });
  await route('/api/workspace/list', { root: '', cases: [] });
  await route('/api/chat/sessions', { sessions: [] });
  await browser('set', 'viewport', '1440', '900');
  await browser('open', server.resolvedUrls.local[0]);
  await browser('wait', '.simulation-guide-action button');
  await browser('eval', `window.__messages = ${JSON.stringify(MESSAGES)}; ${fixture}`);
  await browser('eval', '[...document.querySelectorAll(".nav-item")].find((item) => /settings/i.test(item.textContent)).click()');
  await browser('wait', '.update-card');
  assert.equal(await status(), '아직 확인 안 함.');

  // Check -> Download.
  await browser('click', '.update-actions button');
  await browser('wait', '.update-go');
  assert.equal(await status(), '버전 0.2.0이 있어요.');
  await browser('click', '.update-go');
  await browser('wait', '.update-go');
  assert.equal(await status(), 'v0.2.0를 받았고 서명을 확인했어요.');
  assert.deepEqual(await actions(), ['업데이트 확인', '설치 후 다시 시작']);

  const refusalScreens = [];
  for (const code of ['run_active', 'unconfirmed', 'stop_failed']) {
    await browser('eval', `window.__stopMode = ${JSON.stringify(code)}`);
    await browser('click', '.update-go');
    await until(`document.querySelector(".update-status").textContent.trim() !== "v0.2.0 설치 중."`, `${code} refusal`);
    await new Promise((done) => setTimeout(done, 200));
    // The refusal reason is shown as written, in the live region.
    assert.equal(await status(), MESSAGES[code], code);
    assert.equal(await evaluate('document.querySelector(".update-status").getAttribute("aria-live")'), 'polite');
    // The installer and the relaunch were never reached; the user can try again.
    assert.equal(await count('plugin:updater|install'), 0, `${code}: installer must not run`);
    assert.equal(await count('plugin:process|restart'), 0, `${code}: relaunch must not run`);
    assert.deepEqual(await actions(), ['업데이트 확인', '설치 후 다시 시작'], `${code}: Install must stay available`);
    assert.equal(await evaluate('document.querySelector(".update-go").disabled'), false);
    assert.equal(await evaluate('document.querySelector(".update-actions button").disabled'), false);
    // Keyboard recovery: focus must not be dropped to the page after a refusal.
    refusalScreens.push({ code, focus: await evaluate('document.activeElement.className + "|" + document.activeElement.textContent.trim()') });
    await browser('screenshot', resolve(out, `blocked-${code}-1440.png`));
  }
  assert.ok(refusalScreens.every(({ focus }) => focus.includes('update-go|설치 후 다시 시작')), `focus after a refusal: ${JSON.stringify(refusalScreens)}`);

  // Narrow screens: the longest message, touch size, no sideways scroll, nothing cut off.
  await browser('eval', 'window.__stopMode = "run_active"');
  await browser('click', '.update-go');
  await until(`document.querySelector(".update-status").textContent.trim() !== "v0.2.0 설치 중."`, 'run_active refusal');
  for (const [width, height] of [[390, 780], [320, 640], [720, 450]]) {
    await browser('set', 'viewport', String(width), String(height));
    await new Promise((done) => setTimeout(done, 300));
    await browser('eval', 'document.querySelector(".update-card").scrollIntoView({ block: "end" })');
    await new Promise((done) => setTimeout(done, 200));
    const geometry = await evaluate(`(() => {
      const card = document.querySelector('.update-card').getBoundingClientRect();
      const statusBox = document.querySelector('.update-status').getBoundingClientRect();
      const buttons = [...document.querySelectorAll('.update-actions button')].map((button) => button.getBoundingClientRect());
      return {
        pageOverflow: document.documentElement.scrollWidth - innerWidth,
        statusInsideCard: statusBox.left >= card.left - 1 && statusBox.right <= card.right + 1,
        statusClipped: document.querySelector('.update-status').scrollWidth > document.querySelector('.update-status').clientWidth + 1,
        buttonsInsideCard: buttons.every((box) => box.left >= card.left - 1 && box.right <= card.right + 1),
        minButtonHeight: Math.min(...buttons.map((box) => box.height)),
        minButtonWidth: Math.min(...buttons.map((box) => box.width)),
      };
    })()`);
    await browser('screenshot', resolve(out, `blocked-run_active-${width}.png`));
    assert.ok(geometry.pageOverflow <= 0, `${width}px: sideways scroll ${geometry.pageOverflow}`);
    assert.equal(geometry.statusInsideCard, true, `${width}px: message outside its card`);
    assert.equal(geometry.statusClipped, false, `${width}px: message clipped`);
    assert.equal(geometry.buttonsInsideCard, true, `${width}px: buttons outside the card`);
    if (width <= 720) assert.ok(geometry.minButtonHeight >= 44, `${width}px: touch target ${geometry.minButtonHeight}px`);
  }
  await browser('set', 'viewport', '1440', '900');

  // A stop failure that is not a refusal, and an installer failure after a stop, are errors, not refusals.
  await browser('eval', 'window.__stopMode = "plain"');
  await browser('click', '.update-go');
  await until(`document.querySelector(".update-status").textContent.trim() !== "v0.2.0 설치 중."`, 'plain failure');
  assert.equal(await status(), 'fixture: command stop_sidecar not found', JSON.stringify((await calls()).slice(-6)));
  assert.equal(await count('plugin:updater|install'), 0);
  assert.deepEqual(await actions(), ['업데이트 확인'], 'a non-refusal failure goes back to Check');
  await until('document.activeElement.textContent.trim() === "업데이트 확인"', 'focus on Check after a failure');

  // Control: with a confirmed stop the fixture installer runs exactly once, in order, then relaunch.
  await browser('eval', 'window.__stopMode = "ok"');
  await browser('click', '.update-actions button');
  await browser('wait', '.update-go');
  await browser('click', '.update-go');
  await browser('wait', '.update-go');
  await browser('click', '.update-go');
  await until('window.__tauriCalls.includes("plugin:process|restart")', 'relaunch');
  const order = (await calls()).filter((name) => ['stop_sidecar', 'plugin:updater|install', 'plugin:process|restart'].includes(name));
  assert.deepEqual(order.slice(-3), ['stop_sidecar', 'plugin:updater|install', 'plugin:process|restart']);
  assert.equal(await count('plugin:updater|install'), 1);
  await browser('screenshot', resolve(out, 'control-installing-1440.png'));

  const unexpected = (await calls()).filter((name) => !['plugin:updater|check', 'plugin:updater|download', 'plugin:updater|install', 'plugin:process|restart', 'plugin:resources|close', 'stop_sidecar'].includes(name));
  assert.deepEqual(unexpected, []);
  console.log(`PASS: real UpdatePanel with a fixture Tauri bridge (not a real updater or installer): refusals run_active/unconfirmed/stop_failed show their reason, keep Install available, never call the fixture installer or relaunch; focus ${JSON.stringify(refusalScreens.map((screen) => screen.focus))}; narrow-screen geometry checked at 390, 320 and 720x450.`);
} finally {
  await browser('close').catch(() => undefined);
  await new Promise((done) => server.httpServer.close(done));
}
