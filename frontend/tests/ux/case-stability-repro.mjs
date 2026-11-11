#!/usr/bin/env node
// W1-L2 M13 — case-stability repro (Wave 1, no source edits).
// Walks select-case → Run → preview → Results → Workspace and logs the
// title-pill + explorer-selection state after EVERY transition.
// Gate contract: complete per-transition log + verdict TRIGGER:<t> or NO-REPRO.
// Exits 0 when the log is complete and zero approval traffic was recorded.
// No typing, no sends, no saves, no approval clicks.
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { promisify } from 'node:util';

const exec = promisify(execFile);
const BASE = process.argv[2] || 'http://127.0.0.1:5276';
const OUT = process.argv[3] || '/mnt/c/Users/Woojin/AppData/Local/Temp/olga-ux-audit/ux-impl/W1-L2';
const SESSION = 'olga-w1l2';

const run = async (...args) =>
  (await exec('agent-browser', ['--session', SESSION, ...args], { timeout: 60000 })).stdout.trim();
const evaluate = async (source) => {
  const raw = await run('eval', `JSON.stringify(${source})`);
  // agent-browser prints the eval result JSON-encoded once more.
  const once = JSON.parse(raw);
  return typeof once === 'string' ? JSON.parse(once) : once;
};
const snap = () => evaluate(`({pill: (document.querySelector('.wb-crumb')?.textContent || 'NO-CRUMB').replace(/\\s+/g, ' ').trim().slice(0, 80), current: document.querySelector('.wb-explorer-item[aria-current="true"]')?.getAttribute('aria-label') || null, canvas: document.querySelector('.ws-canvas-name')?.textContent?.trim() || null, view: document.querySelector('.run-panel') ? 'run' : (document.querySelector('#results-inventory-sidebar') ? 'results' : (document.querySelector('.ws-canvas, .ws-empty-state, .ws-selection-state') ? 'workspace' : 'unknown'))})`);

const log = [];
// Rail buttons are clicked by accessible name through the snapshot ref map:
// the real input path, immune to CSS-selector quirks with CJK values.
const clickButton = async (name) => {
  const shot = await run('snapshot');
  const hits = [...shot.matchAll(new RegExp(`- button "${name}" \\[ref=(e\\d+)\\]`, 'g'))].map((m) => m[1]);
  assert.equal(hits.length, 1, `expected exactly one button "${name}", saw ${hits.length}`);
  await run('click', hits[0]);
};
// Live regions (results rail) can detach snapshot refs between resolve and
// click. Re-resolve and re-click until the expected surface appears.
const switchView = async (name, probeJs) => {
  const deadline = Date.now() + 20000;
  let last = false;
  while (Date.now() < deadline) {
    await clickButton(name);
    const t0 = Date.now();
    while (Date.now() - t0 < 4000) {
      last = await evaluate(probeJs);
      if (last) return;
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  assert.ok(last, `view "${name}" never appeared`);
};
const step = async (name, action) => {
  await action();
  const state = await snap();
  log.push({ transition: name, ...state });
  console.log(`${name}: pill=${state.pill} current=${state.current} canvas=${state.canvas} view=${state.view}`);
  await run('screenshot', `${OUT}/w1l2-${log.length - 1}-${name}.png`);
};

await mkdir(OUT, { recursive: true });
let browserStarted = false;
try {
  // Guard: never touch production — identity-check the dev pair first.
  const health = await (await fetch(`${BASE}/health`)).json();
  assert.equal(health.app, 'OLGA Companion');
  assert.equal(health.frontend_port, 5276);
  assert.equal(health.sidecar_port, 8868);
  console.log(`servers OK: vite :${health.frontend_port} + sidecar :${health.sidecar_port}`);

  await run('set', 'viewport', '1280', '800');
  await run('open', BASE);
  await run('wait', '.wb-crumb');
  await run('wait', '.wb-explorer-item');
  await run('wait', '1500');
  browserStarted = true;
  // Record every fetch path; the verdict asserts zero approval traffic.
  await run('eval', 'window.__w1l2reqs = []; window.__w1l2fetch = window.fetch; window.fetch = (...a) => { window.__w1l2reqs.push(String(a[0])); return window.__w1l2fetch(...a); };');
  await step('T0-boot', async () => {});
  await step('T1-select-case', async () => {
    const name = await evaluate(`document.querySelector('.wb-explorer-group .wb-explorer-item')?.getAttribute('aria-label')`);
    console.log(`  clicking: ${name}`);
    assert.match(name || '', /\.genkey/);
    await run('click', '.wb-explorer-group .wb-explorer-item');
    await run('wait', '.ws-canvas-name');
  });
  await step('T2-open-run', async () => {
    await switchView('실행', `!!document.querySelector('.run-panel')`);
    // doPreview silently no-ops until the engine candidate resolves
    // (runReady). Wait for the enabled button, not just the panel.
    await run('wait', '.run-actions .run-btn:not([disabled])');
  });
  await step('T3-preview', async () => {
    try {
      await run('click', '.run-actions .run-btn');
    } catch (cause) {
      // The bottom panel can cover the run actions (P3 F10 neighbour).
      // A user collapses it; the repro does the same and logs the detour.
      if (!String(cause?.stderr || cause?.message || cause).includes('covered')) throw cause;
      await clickButton('하단 패널 숨기기');
      await run('wait', '800');
      log.push({ transition: 'T3a-collapse-panel', ...(await snap()) });
      await run('click', '.run-actions .run-btn');
    }
    await run('wait', '.run-preview-card');
  });
  await step('T4-open-results', async () => {
    await switchView('결과', `!!document.querySelector('#results-inventory-sidebar')`);
  });
  await step('T5-back-workspace', async () => {
    // Any settled workspace surface counts: canvas when the case survived,
    // selection/empty prompt when it did not — both are verdicts, not timeouts.
    await switchView('작업 공간', `!!document.querySelector('.ws-canvas, .ws-empty-state, .ws-selection-state')`);
  });

  const reqs = await evaluate('window.__w1l2reqs');
  const approvalHits = reqs.filter((p) => p.includes('/api/approvals'));
  console.log(`fetch paths: ${reqs.length} total, approval hits: ${approvalHits.length}`);
  assert.equal(approvalHits.length, 0, `approval traffic during repro: ${approvalHits}`);

  // Gate contract (R-r2 M13): a complete per-transition log plus a verdict.
  // A clearing event is a transition that LOSES a previously selected case;
  // a caseless T0 is a precondition, not an event. Exit 0 with TRIGGER or NO-REPRO.
  const had = (s) => /\.genkey/.test(s || '');
  let trigger = null;
  for (let i = 1; i < log.length; i++) {
    if (had(log[i - 1].pill) && !had(log[i].pill)) { trigger = log[i].transition; break; }
  }
  console.log(`FIRST-CLEAR: ${trigger || 'none'}`);
  console.log(trigger ? `TRIGGER: ${trigger}` : 'NO-REPRO');
  for (const t of ['T0-boot', 'T1-select-case', 'T2-open-run', 'T3-preview', 'T4-open-results', 'T5-back-workspace']) {
    assert.ok(log.some((entry) => entry.transition === t), `missing log entry ${t}`);
  }
} catch (error) {
  if (browserStarted) await run('screenshot', `${OUT}/w1l2-failure.png`).catch(() => {});
  throw error;
} finally {
  if (browserStarted) await run('close').catch(() => {});
}
