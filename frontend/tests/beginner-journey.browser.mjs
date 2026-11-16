import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { promisify } from 'node:util';
import { preview } from 'vite';

const exec = promisify(execFile);
const session = `olga-journey-${process.pid}`;
const out = resolve(process.argv[2] || '/tmp/opencode/olga-journey-browser');
const browser = async (...args) => (await exec('agent-browser', ['--session', session, ...args], { timeout: 30000 })).stdout.trim();
const evaluate = async (source) => {
  let result = JSON.parse(await browser('eval', `JSON.stringify(${source})`));
  return typeof result === 'string' ? JSON.parse(result) : result;
};
const route = async (path, body) => {
  await browser('network', 'unroute', `**${path}`);
  return browser('network', 'route', `**${path}`, '--body', JSON.stringify(body));
};
const providers = [{ provider: 'openai', known: true, has_catalog: true, models: [{ id: 'ui-fixture', label: 'UI fixture (not a live provider)' }] }];
const context = { root: '', cases: [], active: { name: null, path: null }, generation: 0 };
const server = await preview({ configFile: 'frontend/vite.config.ts', preview: { host: '127.0.0.1', port: 0, strictPort: true } });
let browserStarted = false;
try {
  await mkdir(out, { recursive: true });
  await browser('open', 'about:blank');
  browserStarted = true;
  await route('/health', { app: 'OLGA Companion', version: '0.1.1', frontend_port: 5273, sidecar_port: 8865, capabilities: {} });
  await route('/api/session/token', { token: 'isolated-ui-fixture-token' });
  await route('/api/providers', { providers });
  await route('/api/workspace/context', context);
  await route('/api/workspace/list', { root: '', cases: [] });
  await route('/api/chat/session', { session_id: 'ui-fixture-session' });
  await route('/api/chat/sessions', { sessions: [] });
  await browser('network', 'route', '**/api/chat', '--abort');
  const url = server.resolvedUrls.local[0];
  await browser('set', 'viewport', '1440', '900');
  await browser('open', url);
  await browser('wait', '.simulation-guide-action button');
  await browser('eval', 'window.__uiRequests = []; window.__uiFetch = window.fetch; window.fetch = (...args) => { const path = String(args[0]); window.__uiRequests.push(path); if (path === "/api/chat" && window.__holdChat) return new Promise((resolve) => { window.__releaseChat = () => resolve(new Response(\'event: done\\ndata: \' + JSON.stringify({text: "UI fixture response, not an OLGA result. ".repeat(300)}) + \'\\n\\n\', {headers: {"Content-Type":"text/event-stream"}})); }); return window.__uiFetch(...args); }');
  await browser('focus', '.simulation-guide-steps button');
  await browser('press', 'Tab');
  await browser('press', 'Enter');
  assert.equal(await evaluate('document.querySelectorAll(".simulation-guide-steps button")[1].getAttribute("aria-pressed")'), 'true');
  assert.equal(await evaluate('document.querySelector(".simulation-guide-action button").textContent.trim()'), '사례 열기');
  await browser('click', '.simulation-guide-action button');
  assert.equal(await evaluate('document.querySelector("main").getAttribute("aria-label")'), 'workspace workbench');
  await browser('click', '.wordmark');
  await browser('click', '.simulation-guide-steps button');
  await browser('click', '.simulation-guide-action button');
  assert.equal(await evaluate('document.activeElement.getAttribute("data-testid")'), 'chat-input');
  assert.equal(await evaluate('document.activeElement.tagName'), 'TEXTAREA');
  assert.match(await evaluate('document.activeElement.value'), /하나씩/);
  assert.equal(await evaluate('document.activeElement.getBoundingClientRect().height >= 88'), true);
  assert.equal(await evaluate('document.activeElement.scrollWidth <= document.activeElement.clientWidth + 1'), true);
  await browser('click', '.composer [aria-label="질문 비우기"]');
  assert.equal(await evaluate('document.activeElement.value'), '');
  assert.equal(await evaluate('document.activeElement.getAttribute("data-testid")'), 'chat-input');
  await browser('fill', '[data-testid=chat-input]', '\n  ');
  await browser('press', 'Control+Enter');
  await browser('click', '.composer [aria-label="질문 비우기"]');
  await browser('click', '.simulation-guide-action button');
  await browser('press', 'Control+End');
  await browser('press', 'Enter');
  assert.match(await evaluate('document.activeElement.value'), /\n/);
  await browser('eval', 'document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {key:"Enter", ctrlKey:true, isComposing:true, bubbles:true})); document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {key:"Enter", ctrlKey:true, keyCode:229, bubbles:true}));');
  assert.equal(await evaluate('window.__uiRequests.filter((path) => path === "/api/chat" || path.startsWith("/api/approvals/")).length'), 0);
  const draft = await evaluate('document.activeElement.value');
  assert.equal(await evaluate('document.querySelector(".simulation-guide-action button").disabled'), true);
  await browser('click', '.simulation-guide-steps li:nth-child(2) button');
  assert.equal(await evaluate('document.querySelector("[data-testid=chat-input]").value'), draft);
  await browser('screenshot', resolve(out, 'prepared-question.png'));
  await browser('eval', 'window.__holdChat = true');
  await browser('focus', '[data-testid=chat-input]');
  await browser('press', 'Control+Enter');
  await browser('wait', '.composer .stop');
  assert.equal(await evaluate('window.__uiRequests.filter((path) => path === "/api/chat").length'), 1);
  await browser('fill', '[data-testid=chat-input]', '다음 질문은 아직 전송하지 않습니다');
  await browser('press', 'Meta+Enter');
  assert.equal(await evaluate('window.__uiRequests.filter((path) => path === "/api/chat").length'), 1);
  await browser('click', '.composer [aria-label="질문 비우기"]');
  await browser('eval', 'window.__releaseChat()');
  await browser('wait', '.timeline > .simulation-guide');
  assert.equal(await evaluate('document.querySelector(".timeline > .simulation-guide").open'), false);
  await browser('eval', 'document.querySelector(".timeline").scrollTop = 0; document.querySelector(".timeline").dispatchEvent(new Event("scroll"))');
  await browser('wait', '[aria-label="최근 대화로 이동"]');
  assert.equal(await evaluate('document.querySelector(".composer-footer").contains(document.querySelector("[aria-label=\\"최근 대화로 이동\\"]"))'), true);
  assert.equal(await evaluate('document.querySelector("[aria-label=\\"최근 대화로 이동\\"]").getBoundingClientRect().top >= document.querySelector("textarea").getBoundingClientRect().bottom'), true);
  await browser('click', '[aria-label="최근 대화로 이동"]');
  await browser('wait', '1200');
  assert.equal(await evaluate('document.querySelector(".timeline").scrollTop > 0'), true);
  await browser('scrollintoview', '.simulation-guide > summary');
  await browser('click', '.simulation-guide > summary');
  assert.equal(await evaluate('document.querySelector(".simulation-guide").open'), true);

  await route('/api/providers', { providers: [] });
  await browser('eval', 'localStorage.removeItem("olga_view")');
  await browser('reload');
  await browser('wait', '.simulation-guide-action button');
  assert.equal(await evaluate('document.querySelector(".simulation-guide-action button").textContent.trim()'), 'AI 연결 설정');
  await browser('click', '.simulation-guide-action button');
  assert.equal(await evaluate('document.querySelector("main").getAttribute("aria-label")'), 'settings workbench');

  await route('/api/providers', { providers });
  const name = '검증용_긴_사례_이름_'.repeat(10) + '.genkey';
  await route('/api/workspace/context', { ...context, active: { name, path: '/ui-fixture/case.genkey' } });
  await browser('eval', 'localStorage.removeItem("olga_view")');
  await browser('set', 'viewport', '390', '844');
  await browser('reload');
  await browser('wait', '.simulation-guide-action button');
  for (const step of ['create', 'edit', 'validate', 'run', 'analyze']) {
    await browser('select', '.simulation-guide-picker select', step);
    assert.equal(await evaluate('document.querySelector(".simulation-guide-action button").textContent.trim()'), '질문 입력하기');
  }
  assert.equal(await evaluate('document.querySelector(".simulation-guide-action button").getBoundingClientRect().bottom <= document.querySelector(".timeline").getBoundingClientRect().bottom'), true);
  await browser('scrollintoview', '.simulation-guide-action button');
  await browser('click', '.simulation-guide-action button');
  await browser('fill', '[data-testid=chat-input]', '긴 질문입니다. '.repeat(200));
  assert.equal(await evaluate('document.querySelector("textarea").scrollHeight > document.querySelector("textarea").clientHeight'), true);
  assert.equal(await evaluate('document.querySelector("textarea").scrollWidth <= document.querySelector("textarea").clientWidth + 1'), true);
  await browser('click', '.composer [aria-label="질문 비우기"]');
  assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
  await browser('screenshot', resolve(out, 'narrow-long-case.png'));
  // Delayed history replay: open chat A (slow), then chat B; A answering last must not win.
  await route('/api/chat/sessions', { sessions: [
    { session_id: 'sess-b', title: 'B 대화', updated_ms: 2 },
    { session_id: 'sess-a', title: 'A 대화', updated_ms: 1 },
  ] });
  await route('/api/chat/session/sess-a', { records: [{ record: 'user', text: '처음 열린 A' }] });
  await route('/api/chat/session/sess-b', { records: [{ record: 'user', text: '처음 열린 B' }] });
  await browser('eval', 'localStorage.removeItem("olga_view"); localStorage.removeItem("olga_last_chat_session")');
  await browser('reload');
  await browser('wait', '.session-rail-toggle');
  await browser('eval', `(() => { const prior = window.fetch; const json = (records) => new Response(JSON.stringify({ records }), { headers: { "Content-Type": "application/json" } }); window.fetch = (...args) => { const path = String(args[0]); if (path === "/api/chat/session/sess-a") return new Promise((resolve) => { window.__releaseA = () => resolve(json([{ record: "user", text: "A의 늦은 응답" }])); }); if (path === "/api/chat/session/sess-b") return Promise.resolve(json([{ record: "user", text: "B의 본문" }])); return prior(...args); }; })()`);
  const openChat = async (title) => {
    await browser('click', '.session-rail-toggle');
    await browser('wait', '.session-item');
    await browser('eval', `[...document.querySelectorAll(".session-item")].find((item) => item.textContent.includes("${title}")).click()`);
  };
  await openChat('A 대화');
  await openChat('B 대화');
  await browser('wait', '1200');
  assert.match(await evaluate('document.querySelector(".timeline").textContent'), /B의 본문|처음 열린 B/, 'B stays on screen while A is still loading');
  await browser('eval', 'window.__releaseA()');
  await browser('wait', '800');
  const afterLate = await evaluate('document.querySelector(".timeline").textContent');
  assert.match(afterLate, /B의 본문|처음 열린 B/);
  assert.doesNotMatch(afterLate, /A의 늦은 응답/, 'a slow earlier chat never replaces the one on screen');
  await browser('network', 'unroute', '**/health');
  await browser('network', 'route', '**/health', '--abort');
  await browser('reload');
  await browser('wait', '1200');
  assert.equal(await evaluate('document.querySelectorAll(".simulation-guide-action button").length'), 0);
  assert.match(await evaluate('document.querySelector(".simulation-guide-detail").textContent'), /다시 시도/);
  assert.equal(await evaluate('document.querySelector("textarea").disabled'), true);
  console.log('PASS: built-app UI with isolated network fixtures: multiline review, newline/IME safety, clear/focus, whitespace and busy guards, exactly-once shortcut submission, draft preservation, case/provider recovery, mobile step selection, long content scrolling, delayed chat A-then-B replay and offline recovery. No real provider or OLGA run was exercised.');
} catch (error) {
  if (browserStarted) {
    await browser('screenshot', resolve(out, 'failure.png')).catch(() => {});
    console.error(await evaluate('({timeline: (() => {const e=document.querySelector(".timeline"); return {height:e?.clientHeight, scrollHeight:e?.scrollHeight, top:e?.scrollTop, bounds:e?.getBoundingClientRect()}})(), action:document.querySelector(".simulation-guide-action button")?.getBoundingClientRect(), composer:document.querySelector(".composer")?.getBoundingClientRect()})').catch(() => null));
  }
  throw error;
} finally {
  if (browserStarted) await browser('close');
  await new Promise((done) => server.httpServer.close(done));
}
