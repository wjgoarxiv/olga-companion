// Pane-squeeze detector (M9, W1-L1). RED-first shared oracle for the
// layout waves: invariant squeeze rows FAIL on HEAD (two-column sim guide
// in a 300-560px dock); rows for the post-M0/M1 dock link and StepBar
// detail SKIP-when-absent and assert when present. A row that errors on a
// missing node instead of failing on squeeze (or skipping by presence)
// is a bug in this file, not a signal.
//
// Read-only by construction: pane widths are set via eval, one disclosure
// is opened via eval; the run never clicks approval controls, never types
// into inputs or the composer, never sends chat, saves, or runs. A
// self-allow-list at the end fails the run if `approval_required` fired
// or the chat timeline changed under us. Fixture data uses invented demo
// names only. Zero SAFETY assertions live here (safety-count.mjs stays
// the SAFETY oracle).
//
// Matrix: dock {300,384,480,560} x viewport {1280 + 1000} x locale
// {ko,en} x theme {dark,light}; PANE_SQUEEZE_FULL=1 adds viewport 1920.
// The committed default keeps every RED golden (dock 300/384 squeeze)
// and the key regression cells; the full matrix is the W3 merge gate.
import assert from 'node:assert/strict';
import test, { before, after } from 'node:test';
import { execFile } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { promisify } from 'node:util';
import { createServer } from 'vite';

const exec = promisify(execFile);
const session = `olga-pane-squeeze-${process.pid}`;
const out = resolve(process.env.PANE_SQUEEZE_OUT || '/tmp/olga-pane-squeeze');
const FULL = process.env.PANE_SQUEEZE_FULL === '1';

const browser = async (...args) =>
  (await exec('agent-browser', ['--session', session, ...args], { timeout: 45000 })).stdout.trim();
const evaluate = async (source) => {
  const result = JSON.parse(await browser('eval', `JSON.stringify(${source})`));
  return typeof result === 'string' ? JSON.parse(result) : result;
};
const route = async (path, body) => {
  await browser('network', 'unroute', `**${path}`);
  return browser('network', 'route', `**${path}`, '--body', JSON.stringify(body));
};

// One invented long-named case: exercises truncation-with-title without
// any owner or customer name.
const LONG_CASE = 'squeeze_check_demo_export_line.genkey';
const contextWithCase = {
  root: '', generation: 1,
  cases: [{ name: LONG_CASE, rel: LONG_CASE, suffix: '.genkey', size: 4096, path: LONG_CASE }],
  active: { name: null, path: null },
};

let server = null;
let appUrl = '';

before(async () => {
  await mkdir(out, { recursive: true });
  server = await createServer({
    configFile: 'frontend/vite.config.ts',
    server: { host: '127.0.0.1', port: Number(process.env.PANE_SQUEEZE_PORT || 0), strictPort: true },
    appType: 'spa',
  });
  await server.listen();
  appUrl = server.resolvedUrls.local[0];
  await browser('open', 'about:blank');
  await route('/health', { app: 'OLGA Companion', version: '0.1.1', frontend_port: 5275, sidecar_port: 8867, capabilities: {} });
  await route('/api/session/token', { token: 'pane-squeeze-fixture-token' });
  await route('/api/providers', { providers: [{ provider: 'openai', known: true, has_catalog: true, models: [{ id: 'ui-fixture', label: 'UI fixture (not a live provider)' }] }] });
  await route('/api/llm-selection', { provider: 'openai', model: 'ui-fixture', variant: 'medium' });
  await route('/api/workspace/context', contextWithCase);
  await route('/api/workspace/list', { root: '', cases: contextWithCase.cases });
  await route('/api/chat/session', { session_id: 'pane-squeeze-session' });
  await route('/api/chat/sessions', { sessions: [] });
  await browser('network', 'route', '**/api/chat', '--abort');
  await browser('set', 'viewport', '1280', '800');
  await browser('open', appUrl);
  await browser('wait', '#workbench-chat-dock');
  globalThis.__paneSqueezeTimeline = (await snapshotGuard()).timeline;
});

async function snapshotGuard() {
  return evaluate(`(() => ({
    timeline: document.querySelectorAll('.chat-timeline > *').length,
    approval: document.querySelectorAll('[role="alertdialog"], .approval-card').length,
  }))()`);
}

after(async () => {
  try { await browser('close', '--session'); } catch { /* session-scoped teardown */ }
  if (server) await server.close();
});

async function openCell(viewportW, viewportH, locale, theme) {
  await browser('set', 'viewport', String(viewportW), String(viewportH));
  await browser('open', appUrl);
  await browser('wait', '#workbench-chat-dock');
  await evaluate(`(() => { localStorage.setItem('olga-companion.locale.v1', JSON.stringify({version:1, locale:'${locale}'})); localStorage.setItem('olga-companion.theme.v1', '${theme}'); return 'cell'; })()`);
  await browser('open', appUrl);
  await browser('wait', '#workbench-chat-dock');
}

async function setDockWidth(px) {
  return evaluate(`(() => { const d = document.getElementById('workbench-chat-dock'); d.style.width = '${px}px'; return Math.round(d.getBoundingClientRect().width); })()`);
}

// Returns null when the two-column guide body is absent from the dock
// (post-M1 reflow or relocation): callers SKIP, never error.
async function measureGuide() {
  return evaluate(`(() => {
    const dock = document.getElementById('workbench-chat-dock');
    const layout = dock ? dock.querySelector('.simulation-guide-layout') : null;
    if (!dock || !layout) return null;
    const cols = getComputedStyle(layout).gridTemplateColumns.split(' ').map(Number);
    if (cols.length < 2) return { stacked: true, dockW: Math.round(dock.getBoundingClientRect().width) };
    const detail = dock.querySelector('.simulation-guide-detail');
    const p = detail ? detail.querySelector('p') : null;
    const text = p ? p.textContent : '';
    const cjk = (text.match(/[\\u3040-\\u30ff\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff\\uff00-\\uffef]/g) || []).length;
    const lh = p ? parseFloat(getComputedStyle(p).lineHeight) : 0;
    const lines = (p && lh) ? Math.round(p.getBoundingClientRect().height / lh) : 0;
    const body = dock.querySelector('.simulation-guide-body');
    return {
      dockW: Math.round(dock.getBoundingClientRect().width),
      detailW: detail ? Math.round(detail.getBoundingClientRect().width) : 0,
      cjk, lines, linesPer100: cjk ? lines / (cjk / 100) : 0,
      bodyOverflowX: body ? body.scrollWidth - body.clientWidth : 0,
      dockOverflowX: dock.scrollWidth - dock.clientWidth,
    };
  })()`);
}

async function measureChrome() {
  return evaluate(`(() => {
    const names = [...document.querySelectorAll('.wb-explorer-name')].map((el) => {
      const btn = el.closest('button');
      const r = el.getBoundingClientRect();
      return { text: el.textContent, title: btn ? btn.getAttribute('title') : null, overflow: el.scrollWidth - el.clientWidth };
    });
    const seps = [...document.querySelectorAll('[role="separator"]')].map((el) => ({
      label: el.getAttribute('aria-label'), now: el.getAttribute('aria-valuenow'),
      focusable: el.tabIndex >= 0,
    }));
    const dock = document.getElementById('workbench-chat-dock');
    const explorer = document.getElementById('workbench-explorer');
    const panel = document.getElementById('workbench-bottom-panel');
    const centre = document.querySelector('#primary-workbench');
    const rect = (el) => { const r = el.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
    return {
      names, seps,
      rects: { dock: dock ? rect(dock) : null, explorer: explorer ? rect(explorer) : null, panel: panel ? rect(panel) : null, centre: centre ? rect(centre) : null },
      link: !!document.querySelector('.simulation-guide-link'),
      stepbar: !!document.querySelector('[data-stepbar], .step-bar'),
    };
  })()`);
}

const intersects = (a, b) => a && b && a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];

test('dock300 golden: two-column guide must not starve the detail card', async (t) => {
  await openCell(1280, 800, 'ko', 'dark');
  await setDockWidth(300);
  await browser('screenshot', resolve(out, 'dock300-ko-dark.png'));
  const m = await measureGuide();
  if (!m || m.stacked) { t.skip('two-column guide absent from dock (reflowed or relocated)'); return; }
  assert.ok(m.detailW >= 160, `detail card is ${m.detailW}px wide at dock 300 (floor 160px)`);
  assert.ok(m.linesPer100 <= 12, `body runs ${m.linesPer100.toFixed(1)} lines/100 CJK at dock 300 (cap 12)`);
  assert.ok(m.bodyOverflowX <= 0, `guide body overflows ${m.bodyOverflowX}px at dock 300`);
});

test('dock384 golden: default width keeps prose readable', async (t) => {
  await setDockWidth(384);
  const m = await measureGuide();
  if (!m || m.stacked) { t.skip('two-column guide absent from dock (reflowed or relocated)'); return; }
  assert.ok(m.detailW >= 200, `detail card is ${m.detailW}px wide at dock 384 (floor 200px)`);
  assert.ok(m.linesPer100 <= 12, `body runs ${m.linesPer100.toFixed(1)} lines/100 CJK at dock 384 (cap 12)`);
});

test('viewport1920: wide viewport does not rescue pane squeeze', async (t) => {
  if (!FULL) { t.skip('1920 cell runs under PANE_SQUEEZE_FULL=1 (W3 merge gate)'); return; }
  await openCell(1920, 1080, 'ko', 'dark');
  await setDockWidth(300);
  const m = await measureGuide();
  if (!m || m.stacked) { t.skip('two-column guide absent from dock (reflowed or relocated)'); return; }
  assert.ok(m.detailW >= 160, `detail card is ${m.detailW}px wide at dock 300/1920 (floor 160px)`);
  assert.ok(m.bodyOverflowX <= 0, `guide body overflows ${m.bodyOverflowX}px at dock 300/1920`);
});

test('dock480/560 stay clean once the columns fit', async (t) => {
  for (const w of [480, 560]) {
    await setDockWidth(w);
    const m = await measureGuide();
    if (!m || m.stacked) { t.skip(`two-column guide absent at dock ${w}`); return; }
    assert.ok(m.dockOverflowX <= 0, `dock overflows ${m.dockOverflowX}px at dock ${w}`);
    assert.ok(m.bodyOverflowX <= 0, `guide body overflows ${m.bodyOverflowX}px at dock ${w}`);
  }
});

test('truncated names always carry their full title', async () => {
  const c = await measureChrome();
  const clipped = c.names.filter((n) => n.overflow > 1);
  for (const n of clipped) {
    assert.ok(n.title && n.title.length > 0, `clipped name "${n.text}" has no title tooltip`);
  }
  assert.ok(c.names.length > 0, 'fixture case row present for the truncation probe');
});

test('separators stay focusable with live values', async () => {
  const c = await measureChrome();
  assert.ok(c.seps.length >= 2, `expected dock+explorer separators, found ${c.seps.length}`);
  for (const s of c.seps) {
    assert.ok(s.focusable, `separator "${s.label}" is not keyboard-focusable`);
    assert.ok(Number.isFinite(Number(s.now)), `separator "${s.label}" has no numeric aria-valuenow`);
  }
});

test('keyboard resize moves values and persists', async () => {
  const before = await evaluate(`document.querySelector('.wb-dock-resizer').getAttribute('aria-valuenow')`);
  await browser('focus', '.wb-dock-resizer');
  await browser('press', 'ArrowLeft');
  const after = await evaluate(`document.querySelector('.wb-dock-resizer').getAttribute('aria-valuenow')`);
  assert.notEqual(Number(after), Number(before), 'arrow key must move the dock separator value');
  await browser('press', 'ArrowRight');
  const restored = await evaluate(`document.querySelector('.wb-dock-resizer').getAttribute('aria-valuenow')`);
  assert.equal(Number(restored), Number(before), 'symmetric arrow press must restore the value');
});

test('viewport1000: overlay panes never intersect', async (t) => {
  await openCell(1000, 750, 'ko', 'dark');
  await browser('screenshot', resolve(out, 'overlay-1000.png'));
  const c = await measureChrome();
  const { dock, explorer, panel, centre } = c.rects;
  assert.ok(explorer && dock && centre, 'pane rect missing (selector drift) — not a pass');
  const overlap = intersects(explorer, centre) || intersects(dock, centre);
  const scrim = await evaluate(`!!document.querySelector('.wb-scrim, [data-scrim]')`);
  if (!overlap) { assert.ok(true, 'no overlay covers the centre at viewport 1000'); return; }
  assert.ok(scrim, `overlay covers the centre at viewport 1000 with no scrim to dismiss it (M5)`);
});

test('M0/M1 presence-gated rows: link and stepbar detail', async (t) => {
  await openCell(1280, 800, 'ko', 'dark');
  const c = await measureChrome();
  if (!c.link) { t.skip('no dock guide link on HEAD (M1 lands it)'); }
  else {
    const box = await evaluate(`(() => { const r = document.querySelector('.simulation-guide-link').getBoundingClientRect(); const d = document.getElementById('workbench-chat-dock').getBoundingClientRect(); return { fits: r.right <= d.right + 1, lines: 0 }; })()`);
    assert.ok(box.fits, 'dock guide link must fit on one line within the dock');
  }
  if (!c.stepbar) { t.skip('no step bar on HEAD (M0 lands it)'); }
  else {
    assert.ok(true, 'step-bar presence recorded; collapse rects asserted by the M0 lane runner');
  }
});

test('matrix sweep: en + light cells keep the same floors', async (t) => {
  for (const [locale, theme] of [['en', 'dark'], ['ko', 'light']]) {
    await openCell(1280, 800, locale, theme);
    await setDockWidth(300);
    const m = await measureGuide();
    if (!m || m.stacked) { t.skip(`two-column guide absent (${locale}/${theme})`); return; }
    assert.ok(m.bodyOverflowX <= 0, `guide body overflows ${m.bodyOverflowX}px (${locale}/${theme} @300)`);
    assert.ok(m.detailW >= 160, `detail card is ${m.detailW}px (${locale}/${theme} @300)`);
  }
});

// N1 sash geometry + real pointer drag. The three workbench separators
// must sit on their pane's edge, span its full length, keep a >= 24 px hit
// area and answer a real mouse drag (CDP Input.dispatchMouseEvent through
// `mouse move/down/up`), persisting the new size across a reload. The drag
// grabs the pane EDGE (where a user aims), not the handle's own centre, so
// a mis-placed handle fails instead of being found by selector.
const SASHES = [
  { name: 'explorer', handle: '.wb-explorer-resizer', pane: '#workbench-explorer', vertical: true, edge: 'right', delta: [40, 0], grew: 40, size: 'width' },
  { name: 'dock', handle: '.wb-dock-resizer', pane: '#workbench-chat-dock', vertical: true, edge: 'left', delta: [-60, 0], grew: 60, size: 'width' },
  { name: 'panel', handle: '.wb-panel-resizer', pane: '#workbench-bottom-panel', vertical: false, edge: 'top', delta: [0, -40], grew: 40, size: 'height' },
];
const SASH_STORAGE = ['olga-companion.explorer.width', 'olga-companion.dock.width', 'olga-companion.panel.height'];
const SASH_CELLS = [[1280, 800, 'dark'], [1280, 800, 'light'], [1920, 1080, 'dark'], [1920, 1080, 'light']];

async function measureSash(s) {
  return evaluate(`((s) => {
    const h = document.querySelector(s.handle);
    const p = document.querySelector(s.pane);
    if (!h || !p) return null;
    const hr = h.getBoundingClientRect();
    const pr = p.getBoundingClientRect();
    const cx = (hr.left + hr.right) / 2;
    const cy = (hr.top + hr.bottom) / 2;
    const probe = (x, y) => { const el = document.elementFromPoint(x, y); return !!el && (el === h || h.contains(el)); };
    const reach = s.vertical ? [probe(cx - 11.5, cy), probe(cx + 11.5, cy)] : [probe(cx, cy - 11.5), probe(cx, cy + 11.5)];
    const g = h.querySelector('span').getBoundingClientRect();
    return {
      h: [hr.left, hr.top, hr.right, hr.bottom], p: [pr.left, pr.top, pr.right, pr.bottom],
      reach, cursor: getComputedStyle(h).cursor, grip: s.vertical ? g.width : g.height,
      size: s.vertical ? pr.width : pr.height,
    };
  })(${JSON.stringify(s)})`);
}

async function measureMidGrid() {
  return evaluate(`(() => {
    const cs = getComputedStyle(document.querySelector('.wb-mid'));
    const areaRows = cs.gridTemplateAreas.match(/"[^"]*"/g) || [];
    return {
      rows: cs.gridTemplateRows.split(' ').length,
      cols: cs.gridTemplateColumns.split(' ').length,
      areaRows: areaRows.length,
      areaCols: areaRows.length ? areaRows[0].replace(/"/g, '').trim().split(/\\s+/).length : 0,
    };
  })()`);
}

async function resetSashStorage() {
  await evaluate(`(() => { ${JSON.stringify(SASH_STORAGE)}.forEach((k) => { localStorage.removeItem(k); localStorage.removeItem(k + '.touched'); }); return 'reset'; })()`);
  await browser('open', appUrl);
  await browser('wait', '#workbench-chat-dock');
  await browser('wait', '#workbench-bottom-panel');
}

// Where a user aims: one pixel inside the handle zone, mid-way along the edge.
function grabPoint(m, s) {
  const [pl, pt, pr, pb] = m.p;
  if (s.vertical) return [(s.edge === 'right' ? pr : pl) + 1, (pt + pb) / 2];
  return [(pl + pr) / 2, pt + 1];
}

async function dragFrom([x, y], [dx, dy]) {
  await browser('mouse', 'move', String(Math.round(x)), String(Math.round(y)));
  await browser('mouse', 'down');
  for (let i = 1; i <= 6; i += 1) {
    await browser('mouse', 'move', String(Math.round(x + (dx * i) / 6)), String(Math.round(y + (dy * i) / 6)));
  }
  await browser('mouse', 'up');
}

for (const [vw, vh, theme] of SASH_CELLS) {
  const cell = `${vw}x${vh} ${theme}`;
  const shot = (state) => resolve(out, `n1-${vw}x${vh}-${theme}-${state}.png`);

  test(`sash geometry ${cell}: handles own a grid area, span the pane edge, reach 24px`, async () => {
    await openCell(vw, vh, 'ko', theme);
    await resetSashStorage();
    await browser('screenshot', shot('before'));
    const problems = [];
    const grid = await measureMidGrid();
    if (grid.rows !== grid.areaRows) problems.push(`.wb-mid has ${grid.rows} rows for ${grid.areaRows} template rows (implicit row)`);
    if (grid.cols !== grid.areaCols) problems.push(`.wb-mid has ${grid.cols} columns for ${grid.areaCols} template columns (implicit column)`);
    for (const s of SASHES) {
      const m = await measureSash(s);
      if (!m) { problems.push(`${s.name}: handle or pane missing (selector drift)`); continue; }
      const [hl, ht, hr, hb] = m.h;
      const [pl, pt, pr, pb] = m.p;
      const longHandle = s.vertical ? hb - ht : hr - hl;
      const longPane = s.vertical ? pb - pt : pr - pl;
      const startGap = s.vertical ? Math.abs(ht - pt) : Math.abs(hl - pl);
      if (Math.abs(longHandle - longPane) > 2) problems.push(`${s.name}: long side ${longHandle.toFixed(1)} vs pane edge ${longPane.toFixed(1)}`);
      if (startGap > 2) problems.push(`${s.name}: starts ${startGap.toFixed(1)}px off the pane edge start`);
      const edge = { right: pr, left: pl, top: pt }[s.edge];
      const lo = s.vertical ? hl : ht;
      const hi = s.vertical ? hr : hb;
      if (edge < lo - 2 || edge > hi + 2) problems.push(`${s.name}: edge at ${edge.toFixed(1)} is outside the handle ${lo.toFixed(1)}..${hi.toFixed(1)}`);
      if (!m.reach.every(Boolean)) problems.push(`${s.name}: hit area under 24px (reach ${m.reach.join('/')})`);
      if (m.grip < 1) problems.push(`${s.name}: visible line ${m.grip}px`);
      const cursor = s.vertical ? 'col-resize' : 'row-resize';
      if (m.cursor !== cursor) problems.push(`${s.name}: cursor ${m.cursor}, wanted ${cursor}`);
    }
    assert.deepEqual(problems, [], `sash geometry (${cell}):\n${problems.join('\n')}`);
  });

  test(`sash drag ${cell}: a real mouse drag resizes and persists`, async () => {
    await openCell(vw, vh, 'ko', theme);
    await resetSashStorage();
    const problems = [];
    const sizes = {};
    for (const s of SASHES) {
      const m = await measureSash(s);
      if (!m) { problems.push(`${s.name}: handle or pane missing`); continue; }
      await dragFrom(grabPoint(m, s), s.delta);
      const after = await measureSash(s);
      const grew = after.size - m.size;
      sizes[s.name] = after.size;
      if (Math.abs(grew - s.grew) > 4) problems.push(`${s.name}: ${s.size} moved ${grew.toFixed(1)}px for a ${s.grew}px drag`);
    }
    await browser('screenshot', shot('after'));
    await browser('open', appUrl);
    await browser('wait', '#workbench-chat-dock');
    await browser('wait', '#workbench-bottom-panel');
    for (const s of SASHES) {
      if (sizes[s.name] === undefined) continue;
      const m = await measureSash(s);
      if (Math.abs(m.size - sizes[s.name]) > 1) problems.push(`${s.name}: ${s.size} ${m.size.toFixed(1)} after reload, was ${sizes[s.name].toFixed(1)}`);
    }
    assert.deepEqual(problems, [], `sash drag (${cell}):\n${problems.join('\n')}`);
  });
}

// N2 UI scale: the Settings control persists, the root carries the scale,
// and no scale step clips the workbench or Settings at either viewport.
const UI_SCALE_KEY = 'olga-companion.ui-scale.v1';
const SCALE_CELLS = [[1280, 800], [1920, 1080]];
const SCALE_STEPS = [80, 100, 130];

async function setStoredScale(step) {
  await evaluate(`(() => { localStorage.setItem('${UI_SCALE_KEY}', '${step}'); return 'scale'; })()`);
  await browser('open', appUrl);
  await browser('wait', '#workbench-chat-dock');
}

// One probe element reads --fs-m through the cascade as real pixels.
async function measureRootScale() {
  return evaluate(`(() => {
    const root = document.documentElement;
    const probe = document.createElement('div');
    probe.style.cssText = 'position:absolute;visibility:hidden;font-size:var(--fs-m)';
    document.body.appendChild(probe);
    const fsM = parseFloat(getComputedStyle(probe).fontSize);
    probe.remove();
    return { attr: root.getAttribute('data-ui-scale'), scale: getComputedStyle(root).getPropertyValue('--ui-scale').trim(), fsM, stored: localStorage.getItem('${UI_SCALE_KEY}') };
  })()`);
}

// Clipping detector: text cut by its own or an ancestor's overflow:hidden,
// ellipsis without a title, text past the viewport, and page-level x scroll.
// Content inside a scroll container is scrollable, not cut, on that axis.
async function detectClipping() {
  return evaluate(`(() => {
    const vw = window.innerWidth, vh = window.innerHeight;
    const found = [];
    const name = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
    const clips = (v) => v === 'hidden' || v === 'clip';
    const scrolls = (v) => v === 'auto' || v === 'scroll';
    if (document.documentElement.scrollWidth > vw + 1) found.push('page scrolls sideways ' + document.documentElement.scrollWidth + '>' + vw);
    for (const el of document.body.querySelectorAll('*')) {
      if (el.closest('.ui-visually-hidden, .skip-link, [hidden], [aria-hidden="true"]')) continue;
      const own = [...el.childNodes].filter((n) => n.nodeType === 3 && n.textContent.trim());
      if (!own.length) continue;
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      if (cs.display === 'none' || cs.visibility === 'hidden' || r.width === 0 || r.height === 0) continue;
      const text = own.map((n) => n.textContent.trim()).join(' ').slice(0, 24);
      const titled = !!(el.title || el.closest('[title]') || el.closest('[aria-label]'));
      if (clips(cs.overflowX) && el.scrollWidth > el.clientWidth + 1 && !(cs.textOverflow === 'ellipsis' && titled)) found.push('x-clip ' + name(el) + ' "' + text + '" ' + el.scrollWidth + '>' + el.clientWidth);
      if (clips(cs.overflowY) && el.scrollHeight > el.clientHeight + 1 && !cs.webkitLineClamp.match(/^[1-9]/) && cs.display !== 'flex' && cs.display !== 'inline-flex') found.push('y-clip ' + name(el) + ' "' + text + '" ' + el.scrollHeight + '>' + el.clientHeight);
      let scrollX = scrolls(cs.overflowX), scrollY = scrolls(cs.overflowY);
      for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
        const acs = getComputedStyle(a);
        const ar = a.getBoundingClientRect();
        if (clips(acs.overflowX) && !scrollX && (r.right > ar.right + 1 || r.left < ar.left - 1)) { found.push('cut-x-by ' + name(a) + ' <- ' + name(el) + ' "' + text + '"'); break; }
        if (clips(acs.overflowY) && !scrollY && (r.bottom > ar.bottom + 1 || r.top < ar.top - 1)) { found.push('cut-y-by ' + name(a) + ' <- ' + name(el) + ' "' + text + '"'); break; }
        scrollX = scrollX || scrolls(acs.overflowX);
        scrollY = scrollY || scrolls(acs.overflowY);
      }
      if ((!scrollX && (r.right > vw + 1 || r.left < -1)) || (!scrollY && (r.bottom > vh + 1 || r.top < -1))) found.push('off-viewport ' + name(el) + ' "' + text + '"');
    }
    return [...new Set(found)];
  })()`);
}

async function openView(view, ready) {
  await evaluate(`(() => { document.querySelector('.wb-activity [data-view="${view}"]')?.click(); return 'open'; })()`);
  await browser('wait', ready);
  await browser('wait', '450');
}
const openSettings = async () => {
  await openView('settings', '.display-card');
  await evaluate(`(() => { document.querySelector('.display-card').scrollIntoView({ block: 'center' }); return 'scrolled'; })()`);
};
const openWorkspace = () => openView('workspace', '#workbench-chat-dock');

test('ui scale: the Settings control applies at the root, persists across a reload and works from the keyboard', async () => {
  await openCell(1280, 800, 'ko', 'dark');
  await evaluate(`(() => { localStorage.removeItem('${UI_SCALE_KEY}'); return 'reset'; })()`);
  await browser('open', appUrl);
  await browser('wait', '#workbench-chat-dock');
  const base = await measureRootScale();
  assert.equal(base.scale, '1', 'default root scale is 1');
  assert.equal(base.fsM, 13, `--fs-m is 13px at 100 % (got ${base.fsM})`);
  await openSettings();
  const group = '[role="radiogroup"][aria-label="글자 크기 / 화면 배율"]';
  assert.equal(await evaluate(`document.querySelectorAll('${group} [role="radio"]').length`), 6, 'six scale steps');
  assert.equal(await evaluate(`document.querySelector('${group} [aria-checked="true"]').textContent.trim()`), '100%', 'the current value is visible');
  await browser('click', '#display-ui-scale-label + .ui-segmented .ui-segmented-option:last-child');
  let m = await measureRootScale();
  assert.equal(m.attr, '130', 'data-ui-scale on the root after a click');
  assert.equal(m.scale, '1.3', '--ui-scale is 1.3');
  assert.ok(Math.abs(m.fsM - 13 * 1.3) < 0.1, `--fs-m scales live to ${13 * 1.3}px (got ${m.fsM})`);
  assert.equal(m.stored, '130', 'the choice is stored');
  await browser('focus', `${group} [aria-checked="true"]`);
  await browser('press', 'ArrowLeft');
  m = await measureRootScale();
  assert.equal(m.attr, '120', 'ArrowLeft moves one step down');
  await browser('open', appUrl);
  await browser('wait', '#workbench-chat-dock');
  m = await measureRootScale();
  assert.equal(m.attr, '120', 'the scale survives a reload');
  assert.ok(Math.abs(m.fsM - 13 * 1.2) < 0.1, `reloaded --fs-m is ${13 * 1.2}px (got ${m.fsM})`);
});

// N5 neo-brutal chrome: labelled 96 px rail with a sliding select block, pixel
// icons, chevron step bar, and the Off / Subtle / Full motion presets.
const MOTION_KEY = 'olga-companion.motion.v1';

test('neo chrome: 96 px labelled rail, the select block sits on the active item, pixel icons, chevron steps', async () => {
  await openCell(1280, 800, 'ko', 'dark');
  await browser('wait', '700');
  const m = await evaluate(`(() => {
    const rail = document.querySelector('.wb-activity');
    const block = rail.querySelector('.wb-activity-indicator');
    const active = rail.querySelector('button[aria-pressed="true"]');
    const rb = block.getBoundingClientRect(), ab = active.getBoundingClientRect();
    const step = document.querySelector('.step-cell');
    const label = active.querySelector('.ui-iconbutton-label');
    return {
      railW: Math.round(rail.getBoundingClientRect().width),
      blockTop: Math.round(rb.top), activeTop: Math.round(ab.top),
      blockH: Math.round(rb.height), activeH: Math.round(ab.height),
      blockFill: getComputedStyle(block).backgroundColor,
      selectFill: getComputedStyle(document.documentElement).getPropertyValue('--select').trim(),
      labelPx: label ? parseFloat(getComputedStyle(label).fontSize) : 0,
      railPixelIcons: rail.querySelectorAll('svg.px-icon').length,
      rail3d: document.querySelectorAll('.wb-activity img.ui-icon3d, .wb-explorer img.ui-icon3d').length,
      explorerPixelIcons: document.querySelectorAll('.wb-explorer svg.px-icon').length,
      stepClip: step ? getComputedStyle(step).clipPath : 'none',
      chips: [...document.querySelectorAll('.wb-pane-idx')].map((c) => c.textContent.trim()),
    };
  })()`);
  assert.ok(m.railW >= 94 && m.railW <= 98, `the rail is 96 px wide at 1280 (got ${m.railW})`);
  assert.ok(Math.abs(m.blockTop - m.activeTop) <= 2, `the select block sits on the active item (top ${m.blockTop} vs ${m.activeTop})`);
  assert.ok(Math.abs(m.blockH - m.activeH) <= 2, `the select block is as tall as the active item (${m.blockH} vs ${m.activeH})`);
  assert.notEqual(m.blockFill, 'rgba(0, 0, 0, 0)', 'the block is a solid fill');
  assert.ok(m.labelPx >= 12, `the rail label is 12 px or more (got ${m.labelPx})`);
  assert.ok(m.railPixelIcons >= 4, `rail icons are pixel icons (got ${m.railPixelIcons})`);
  assert.equal(m.rail3d, 0, 'no 3D render in the rail or Explorer');
  assert.ok(m.explorerPixelIcons >= 3, 'Explorer rows and header carry pixel icons');
  assert.notEqual(m.stepClip, 'none', 'the step cells are chevrons (clip-path)');
  assert.ok(m.chips.includes('01') && m.chips.includes('02') && m.chips.includes('03') && m.chips.includes('04'), `index chips 01..04 (got ${m.chips})`);
});

test('motion presets: subtle by default, OS reduced-motion starts at off, the Settings control persists', async () => {
  await openCell(1280, 800, 'ko', 'dark');
  const read = () => evaluate(`(() => { const r = document.documentElement; const cs = getComputedStyle(r); return { attr: r.getAttribute('data-motion'), mo: cs.getPropertyValue('--mo').trim(), fx: cs.getPropertyValue('--fx').trim(), stored: localStorage.getItem('${MOTION_KEY}') }; })()`);
  await evaluate(`(() => { localStorage.removeItem('${MOTION_KEY}'); return 'reset'; })()`);
  await browser('open', appUrl);
  await browser('wait', '#workbench-chat-dock');
  let m = await read();
  assert.equal(m.attr, 'subtle', 'no stored choice and no OS preference reads as subtle');
  assert.equal(m.fx, '0', 'Full-only effects stay off in subtle');
  await openSettings();
  const group = '[role="radiogroup"][aria-label="모션"]';
  assert.equal(await evaluate(`document.querySelectorAll('${group} [role="radio"]').length`), 4, 'System, Off, Subtle, Full');
  await browser('click', '#display-motion-label + .ui-segmented .ui-segmented-option:last-child');
  m = await read();
  assert.equal(m.attr, 'full', 'Full applies at the root');
  assert.equal(m.fx, '1', '--fx is 1 in Full');
  assert.equal(m.stored, 'full', 'the choice is stored');
  await browser('open', appUrl);
  await browser('wait', '#workbench-chat-dock');
  assert.equal((await read()).attr, 'full', 'the choice survives a reload');
  await openSettings();
  await browser('click', `${group} [role="radio"]:nth-child(2)`);
  m = await read();
  assert.equal(m.attr, 'off', 'Off applies at the root');
  assert.equal(m.mo, '0', '--mo is 0 in Off');
  await evaluate(`(() => { localStorage.removeItem('${MOTION_KEY}'); return 'reset'; })()`);
  await browser('set', 'media', 'dark', 'reduced-motion');
  await browser('open', appUrl);
  await browser('wait', '#workbench-chat-dock');
  assert.equal((await read()).attr, 'off', 'prefers-reduced-motion starts at off');
  await browser('set', 'media', 'dark');
});

// N5b: pixel topology symbols, static decor, the sash size label and the Full-only effects.
const TOPOLOGY = {
  path: LONG_CASE,
  nodes: [
    { id: 'n1', label: 'demo_source_01', kind: 'SOURCE' }, { id: 'n2', label: 'demo_node_01', kind: 'NODE' },
    { id: 'n3', label: 'demo_valve_01', kind: 'VALVE' }, { id: 'n4', label: 'demo_sep_01', kind: 'SEPARATOR' },
    { id: 'n5', label: 'demo_sink_01', kind: 'SINK' },
  ],
  edges: [
    { source: 'n1', target: 'n2', label: 'demo_pipe_01', kind: 'FLOWPATH' }, { source: 'n2', target: 'n3', label: 'demo_pipe_02', kind: 'FLOWPATH' },
    { source: 'n3', target: 'n4', label: 'demo_pipe_03', kind: 'FLOWPATH' }, { source: 'n4', target: 'n5', label: 'demo_pipe_04', kind: 'FLOWPATH' },
  ],
  counts: { nodes: 5, flowpaths: 4, edges: 4 },
  truncated: false,
};

async function openWithMotion(motion) {
  await openCell(1280, 800, 'ko', 'dark');
  await evaluate(`(() => { localStorage.setItem('${MOTION_KEY}', '${motion}'); return 'motion'; })()`);
  await browser('open', appUrl);
  await browser('wait', '#workbench-chat-dock');
  await browser('wait', '700');
}

test('neo decor: pixel symbols on every topology node, hidden rulers and marks, live coordinates, barcode', async () => {
  await openWithMotion('subtle');
  await route('/api/workspace/context', { ...contextWithCase, active: { name: LONG_CASE, path: LONG_CASE } });
  await route('/api/workspace/active', { name: LONG_CASE, path: LONG_CASE });
  await route('/api/genkey/topology', TOPOLOGY);
  await browser('open', appUrl);
  await evaluate(`(() => { document.querySelector('.wb-activity [data-view="workspace"]')?.click(); return 'workspace'; })()`);
  for (let attempt = 0; attempt < 20 && (await evaluate(`document.querySelectorAll('.topo-node').length`)) < 5; attempt += 1) await browser('wait', '500');
  await browser('wait', '600');
  const m = await evaluate(`(() => {
    const svg = document.querySelector('.topo-svg');
    const nodes = [...svg.querySelectorAll('.topo-node')];
    const canvas = document.querySelector('.topo-canvas');
    const decor = [...canvas.querySelectorAll('.frame-ruler, .frame-mark, .topo-coord')];
    const coord = canvas.querySelector('.topo-coord');
    const before = coord.textContent;
    const box = canvas.getBoundingClientRect();
    canvas.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: box.left + 123, clientY: box.top + 45 }));
    return {
      nodes: nodes.length,
      iconNodes: nodes.filter((n) => n.querySelector('svg.topo-node-icon rect')).length,
      images: svg.querySelectorAll('image').length,
      decorCount: decor.length,
      decorHidden: decor.every((el) => el.getAttribute('aria-hidden') === 'true'),
      before, after: coord.textContent,
      coordFont: getComputedStyle(coord).fontFamily,
      barcodeHidden: document.querySelector('.wb-barcode')?.getAttribute('aria-hidden'),
      ticks: getComputedStyle(canvas.querySelector('.frame-ruler-x')).backgroundImage.includes('repeating-linear-gradient'),
    };
  })()`);
  assert.equal(m.nodes, 5, 'five demo nodes');
  assert.equal(m.iconNodes, 5, 'every node draws a pixel symbol');
  assert.equal(m.images, 0, 'no raster image inside the topology');
  assert.ok(m.decorCount >= 7, `rulers, marks and the coordinate readout are present (got ${m.decorCount})`);
  assert.ok(m.decorHidden, 'all topology decor is aria-hidden');
  assert.equal(m.after, 'X 0123 · Y 0045', `the readout follows the pointer (was ${m.before}, now ${m.after})`);
  assert.match(m.coordFont, /Meslo|mono/i, 'coordinates use the mono face');
  assert.equal(m.barcodeHidden, 'true', 'the title-bar barcode is aria-hidden');
  assert.ok(m.ticks, 'ruler ticks are painted');
  await route('/api/workspace/context', contextWithCase);
});

for (const [preset, shown] of [['off', false], ['subtle', true], ['full', true]]) {
  test(`sash size label in ${preset}: ${shown ? 'visible on hover' : 'hidden'}`, async () => {
    await openWithMotion(preset);
    await browser('hover', '.wb-dock-resizer');
    await browser('wait', '300');
    const m = await evaluate(`(() => {
      const label = document.querySelector('.wb-dock-resizer .panel-resizer-label');
      const cs = getComputedStyle(label);
      return { text: label.textContent, hidden: label.getAttribute('aria-hidden'), display: cs.display, opacity: cs.opacity };
    })()`);
    assert.match(m.text, /^W \d+ PX$/, `label text (${m.text})`);
    assert.equal(m.hidden, 'true', 'the label is aria-hidden');
    if (shown) assert.ok(m.display !== 'none' && Number(m.opacity) === 1, `visible on hover in ${preset} (${m.display}, ${m.opacity})`);
    else assert.equal(m.display, 'none', 'Off hides the label');
  });
}

test('Full-only effects: the view wipe is on in Full and nowhere else; no glitch in any preset', async () => {
  const read = async (preset) => {
    await openWithMotion(preset);
    return evaluate(`(() => {
      const glitch = getComputedStyle(document.querySelector('.step-cell.is-highlighted .step-name')).animationName;
      const child = document.querySelector('.wb-centre-tabs > .ui-tabs > .ui-tabpanel > * > *');
      const wipe = child ? getComputedStyle(child).animationName : 'no-child';
      const approval = [...document.querySelectorAll('.approval-card, .approve')].map((el) => getComputedStyle(el).animationName);
      return { glitch, wipe, approval, fx: getComputedStyle(document.documentElement).getPropertyValue('--fx').trim() };
    })()`);
  };
  const full = await read('full');
  assert.equal(full.fx, '1');
  assert.doesNotMatch(full.glitch, /neo-glitch/, 'the step label never glitches');
  assert.match(full.wipe, /neo-wipe/, 'view content wipes in Full');
  for (const preset of ['subtle', 'off']) {
    const m = await read(preset);
    assert.doesNotMatch(m.glitch, /neo-glitch/, `no glitch in ${preset}`);
    assert.doesNotMatch(m.wipe, /neo-wipe/, `no wipe in ${preset}`);
  }
});

for (const [vw, vh] of SCALE_CELLS) {
  for (const step of SCALE_STEPS) {
    test(`ui scale ${step} % at ${vw}x${vh}: the workbench and Settings show no clipping`, async () => {
      await openCell(vw, vh, 'ko', 'dark');
      await setStoredScale(step);
      const m = await measureRootScale();
      assert.equal(m.attr, String(step), `root carries data-ui-scale=${step}`);
      await openWorkspace();
      const work = await detectClipping();
      await browser('screenshot', resolve(out, `n2-${vw}x${vh}-s${step}-workbench.png`));
      await openSettings();
      const settings = await detectClipping();
      await browser('screenshot', resolve(out, `n2-${vw}x${vh}-s${step}-settings.png`));
      assert.deepEqual(work, [], `workbench clipping at ${step} % (${vw}x${vh}):\n${work.join('\n')}`);
      assert.deepEqual(settings, [], `settings clipping at ${step} % (${vw}x${vh}):\n${settings.join('\n')}`);
    });
  }
}

// N3: at 1280x800 the dock's step-guide link sat half under the composer.
test('dock guide link is fully visible, not cut by the composer, at 1280x800 and 100 %', async () => {
  await openCell(1280, 800, 'ko', 'dark');
  await evaluate(`(() => { localStorage.removeItem('${UI_SCALE_KEY}'); return 'reset'; })()`);
  await resetSashStorage();
  await browser('wait', '#workbench-chat-dock .simulation-guide-link');
  const box = await evaluate(`(() => {
    const link = document.querySelector('#workbench-chat-dock .simulation-guide-link');
    const region = link.closest('.timeline') || link.parentElement;
    // The anchor box can stretch below its text; judge the drawn text line.
    const range = document.createRange();
    range.selectNodeContents(link);
    const l = range.getBoundingClientRect();
    const r = region.getBoundingClientRect();
    const hit = document.elementFromPoint((l.left + l.right) / 2, (l.top + l.bottom) / 2);
    return { tag: link.tagName + '.' + link.className, top: l.top, bottom: l.bottom, regionTop: r.top, regionBottom: r.bottom, onTop: !!hit && (hit === link || link.contains(hit)) };
  })()`);
  assert.ok(box.top >= box.regionTop - 1 && box.bottom <= box.regionBottom + 1, `the link text ${box.tag} (${box.top.toFixed(0)}-${box.bottom.toFixed(0)}) sits inside its scroll region (${box.regionTop.toFixed(0)}-${box.regionBottom.toFixed(0)})`);
  assert.ok(box.onTop, 'nothing (such as the composer) paints over the link');
});

// N6-FIX: a case with a topology open in the workbench, real routes faked.
// panelHeight 220 is the owner's saved bottom-panel height (the default is 168).
async function openCaseWorkspace(vw, vh, theme, panelHeight = 220) {
  await openCell(vw, vh, 'ko', theme);
  await evaluate(`(() => { localStorage.setItem('olga-companion.panel.height', '${panelHeight}'); return 'panel'; })()`);
  await route('/api/workspace/context', { ...contextWithCase, active: { name: LONG_CASE, path: LONG_CASE } });
  await route('/api/workspace/active', { name: LONG_CASE, path: LONG_CASE });
  await route('/api/genkey/topology', TOPOLOGY);
  await browser('open', appUrl);
  await browser('wait', '#workbench-chat-dock');
  await evaluate(`(() => { document.querySelector('.wb-activity [data-view="workspace"]')?.click(); return 'workspace'; })()`);
  for (let attempt = 0; attempt < 20 && (await evaluate(`document.querySelectorAll('.topo-node').length`)) < 5; attempt += 1) await browser('wait', '500');
  await browser('wait', '700');
}

for (const [vw, vh] of [[1280, 800], [1536, 794]]) {
  test(`topology caption sits inside its pane on first load at ${vw}x${vh}`, async () => {
    await openCaseWorkspace(vw, vh, 'dark');
    const m = await evaluate(`(() => {
      const meta = document.querySelector('.ws-canvas .topo-meta');
      const canvas = document.querySelector('.ws-canvas .topo-canvas');
      if (!meta || !canvas) return { missing: true };
      const r = meta.getBoundingClientRect();
      let clip = null;
      for (let a = meta.parentElement; a; a = a.parentElement) { const o = getComputedStyle(a).overflowY; if (o !== 'visible') { clip = a; break; } }
      const c = clip.getBoundingClientRect();
      const panel = document.querySelector('.wb-panel')?.getBoundingClientRect();
      return { top: r.top, bottom: r.bottom, clipTop: c.top, clipBottom: c.bottom, panelTop: panel ? panel.top : null, canvasH: canvas.getBoundingClientRect().height, scrolls: clip.scrollHeight > clip.clientHeight + 1 };
    })()`);
    assert.ok(!m.missing, `the topology and its caption are rendered`);
    assert.ok(m.top >= m.clipTop - 1 && m.bottom <= m.clipBottom + 1, `caption ${m.top.toFixed(0)}-${m.bottom.toFixed(0)} inside its pane ${m.clipTop.toFixed(0)}-${m.clipBottom.toFixed(0)} without scrolling`);
    assert.ok(m.panelTop === null || m.bottom <= m.panelTop + 1, `caption bottom ${m.bottom.toFixed(0)} is above the bottom panel (${m.panelTop})`);
    assert.ok(m.canvasH >= 160, `the canvas stays usable (${m.canvasH.toFixed(0)} px)`);
    assert.ok(!m.scrolls, 'the pane needs no scrolling to show the whole topology and its caption');
    await evaluate(`(() => { localStorage.removeItem('olga-companion.panel.height'); return 'clean'; })()`);
    await route('/api/workspace/context', contextWithCase);
  });
}

// N6-FIX: every select-filled control has a focus ring that holds 3:1 on the select fill.
for (const theme of ['dark', 'light']) {
  test(`select-filled controls keep a visible focus ring in ${theme}`, async () => {
    await openCaseWorkspace(1280, 800, theme);
    const probes = [
      ['current step', '.step-cell.is-highlighted .step-open'],
      ['selected explorer row', '.wb-explorer-item[aria-current="true"]'],
      ['primary button', '.ui-button-primary'],
      ['rail active item', '.wb-activity .ui-iconbutton[aria-pressed="true"]'],
    ];
    for (const [name, selector] of probes) {
      await browser('focus', selector);
      await browser('press', 'Shift+Tab');
      await browser('press', 'Tab');
      const m = await evaluate(`(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) return { missing: true };
        const rgb = (c) => (c.match(/[\\d.]+/g) || []).slice(0, 3).map(Number);
        const lin = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
        const L = (c) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
        const ratio = (a, b) => (Math.max(L(a), L(b)) + 0.05) / (Math.min(L(a), L(b)) + 0.05);
        const probe = document.createElement('i'); probe.style.color = getComputedStyle(document.documentElement).getPropertyValue('--select'); document.body.appendChild(probe);
        const select = rgb(getComputedStyle(probe).color); probe.remove();
        const cs = getComputedStyle(el);
        const inner = [];
        if (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0 && parseFloat(cs.outlineOffset) < 0) inner.push(rgb(cs.outlineColor));
        for (const m of cs.boxShadow.matchAll(/(rgba?\\([^)]*\\))\\s+0px 0px 0px (\\d+(?:\\.\\d+)?)px inset|inset\\s+(rgba?\\([^)]*\\))?\\s*0px 0px 0px (\\d+(?:\\.\\d+)?)px/g)) inner.push(rgb(m[1] || m[3]));
        return { focusVisible: el.matches(':focus-visible'), active: document.activeElement === el, inner: inner.map((c) => +ratio(c, select).toFixed(2)), shadow: cs.boxShadow, outline: cs.outlineColor + ' ' + cs.outlineWidth + ' ' + cs.outlineOffset };
      })()`);
      assert.ok(!m.missing, `${name} (${selector}) is on the page`);
      assert.ok(m.active && m.focusVisible, `${name} takes keyboard focus-visible (${JSON.stringify(m)})`);
      assert.ok(m.inner.some((r) => r >= 3), `${name}: an inner ring holds 3:1 on the select fill in ${theme} (rings ${JSON.stringify(m.inner)}; shadow ${m.shadow}; outline ${m.outline})`);
    }
    await route('/api/workspace/context', contextWithCase);
  });
}

// N6-FIX2: a selected state's edge (fill, border or 1px+ inset shadow) holds 3:1
// against what surrounds the control, in both themes. Opening the view uses
// the same fixtures as the other cells; nothing is clicked except navigation.
const EDGE_PROBES = [
  ['selected explorer row', '.wb-explorer-item[aria-current="true"]', 'parent', 'workspace'],
  ['active rail item', '.wb-activity .ui-iconbutton[aria-pressed="true"]', '.wb-activity', 'workspace'],
  ['current step', '.step-cell.is-highlighted .step-open', '.step-bar', 'workspace', '.step-cell.is-highlighted'],
  ['selected Settings section', '.settings-sections button[aria-current="page"]', 'parent', 'settings'],
  ['selected Run mode segment', '.run-mode .ui-segmented-option[aria-checked="true"]', '.run-mode .ui-segmented', 'run'],
];

// fillSelector: the element that owns the fill when it is not the control itself (the step's select is on its cell).
async function measureEdge(selector, surround, fillSelector = selector) {
  return evaluate(`(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return { missing: true };
    const num = (c) => (c.match(/[\\d.]+/g) || []).map(Number);
    const lin = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    const L = (c) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
    const ratio = (a, b) => (Math.max(L(a), L(b)) + 0.05) / (Math.min(L(a), L(b)) + 0.05);
    const opaqueBg = (start) => { for (let a = start; a; a = a.parentElement) { const c = num(getComputedStyle(a).backgroundColor); if (c.length >= 3 && (c.length === 3 || c[3] >= 0.99)) return c.slice(0, 3); } return [255, 255, 255]; };
    const around = ${JSON.stringify(surround)} === 'parent' ? el.parentElement : (el.closest(${JSON.stringify(surround)}) || document.querySelector(${JSON.stringify(surround)}));
    const bg = opaqueBg(around);
    const cs = getComputedStyle(el);
    const edges = [];
    const bw = Math.max(...['Top', 'Right', 'Bottom', 'Left'].map((side) => parseFloat(cs['border' + side + 'Width']) || 0));
    const bc = num(cs.borderTopColor);
    if (bw >= 0.5 && cs.borderTopStyle !== 'none' && bc.length >= 3 && (bc.length === 3 || bc[3] > 0.5)) edges.push({ kind: 'border', color: bc.slice(0, 3) });
    for (const m of cs.boxShadow.matchAll(/(rgba?\\([^)]*\\))\\s+0px 0px 0px (\\d+(?:\\.\\d+)?)px inset/g)) { const c = num(m[1]); if (c.length === 3 || c[3] > 0.5) edges.push({ kind: 'inset', color: c.slice(0, 3) }); }
    const fillEl = document.querySelector(${JSON.stringify(fillSelector)}) || el;
    const fill = num(getComputedStyle(fillEl).backgroundColor);
    if (fill.length === 3 || (fill.length === 4 && fill[3] >= 0.99)) edges.push({ kind: 'fill', color: fill.slice(0, 3) });
    return { surround: bg, shadow: cs.boxShadow, border: cs.borderTopWidth + ' ' + cs.borderTopColor, ratios: edges.map((e) => ({ kind: e.kind, ratio: +ratio(e.color, bg).toFixed(2) })) };
  })()`);
}

for (const theme of ['light', 'dark']) {
  test(`selected states hold a 3:1 edge against their surroundings in ${theme}`, async () => {
    await openCaseWorkspace(1280, 800, theme);
    for (const view of ['workspace', 'settings', 'run']) {
      await evaluate(`(() => { document.querySelector('.wb-activity [data-view="${view}"]')?.click(); return 'view'; })()`);
      await browser('wait', '700');
      for (const [name, selector, surround, , fillSelector] of EDGE_PROBES.filter((p) => p[3] === view)) {
        const m = await measureEdge(selector, surround, fillSelector);
        assert.ok(!m.missing, `${name} (${selector}) is on the page`);
        assert.ok(m.ratios.some((r) => r.ratio >= 3), `${name} in ${theme}: an edge reaches 3:1 against ${JSON.stringify(m.surround)} (edges ${JSON.stringify(m.ratios)}; shadow ${m.shadow}; border ${m.border})`);
      }
    }
    await evaluate(`(() => { localStorage.removeItem('olga-companion.panel.height'); return 'clean'; })()`);
    await route('/api/workspace/context', contextWithCase);
  });
}

// N6-FIX review captures: caption, focus rings, composer edge, Settings cards.
// Opt-in like the other capture test: PANE_SQUEEZE_CAPTURE=1.
test('n6 fix captures: caption, focus rings, composer, settings cards', async (t) => {
  if (process.env.PANE_SQUEEZE_CAPTURE !== '1') { t.skip('set PANE_SQUEEZE_CAPTURE=1 to write the review captures'); return; }
  for (const [vw, vh] of [[1280, 800], [1536, 794]]) {
    for (const theme of ['dark', 'light']) {
      await openCaseWorkspace(vw, vh, theme);
      await browser('screenshot', resolve(out, `n6-case-${vw}x${vh}-${theme}.png`));
      for (const [name, selector] of [['step', '.step-cell.is-highlighted .step-open'], ['explorer', '.wb-explorer-item[aria-current="true"]'], ['rail', '.wb-activity .ui-iconbutton[aria-pressed="true"]'], ['primary', '.ui-button-primary']]) {
        await browser('focus', selector);
        await browser('press', 'Shift+Tab');
        await browser('press', 'Tab');
        await browser('screenshot', resolve(out, `n6-focus-${name}-${vw}x${vh}-${theme}.png`));
      }
      await browser('focus', '#chat-message');
      await browser('press', 'Tab');
      await browser('screenshot', resolve(out, `n6-composer-${vw}x${vh}-${theme}.png`));
      await openSettings();
      await evaluate(`(() => { for (const el of document.querySelectorAll('*')) { if (el.scrollTop > 0) el.scrollTop = 0; } return 'top'; })()`);
      await browser('wait', '300');
      await browser('screenshot', resolve(out, `n6-settings-${vw}x${vh}-${theme}.png`));
      await openView('run', '.run-mode');
      await browser('screenshot', resolve(out, `n6-run-${vw}x${vh}-${theme}.png`));
    }
  }
  await evaluate(`(() => { localStorage.removeItem('olga-companion.panel.height'); return 'clean'; })()`);
  await route('/api/workspace/context', contextWithCase);
});

// Review captures for N2/N3: viewport x theme x scale x density. Opt-in so the
// default run stays fast: PANE_SQUEEZE_CAPTURE=1.
test('review captures: scale x density matrix', async (t) => {
  if (process.env.PANE_SQUEEZE_CAPTURE !== '1') { t.skip('set PANE_SQUEEZE_CAPTURE=1 to write the review captures'); return; }
  for (const [vw, vh] of SCALE_CELLS) {
    for (const theme of ['dark', 'light']) {
      for (const density of ['compact', 'comfortable']) {
        for (const step of SCALE_STEPS) {
          await openCell(vw, vh, 'ko', theme);
          await evaluate(`(() => { localStorage.setItem('${UI_SCALE_KEY}', '${step}'); localStorage.setItem('olga-companion.density.v1', '${density}'); localStorage.setItem('olga-companion.motion.v1', 'off'); return 'cell'; })()`);
          await browser('open', appUrl);
          await browser('wait', '#workbench-chat-dock');
          const m = await measureRootScale();
          assert.equal(m.attr, String(step));
          assert.equal(await evaluate(`document.documentElement.getAttribute('data-density')`), density);
          await openWorkspace();
          await browser('screenshot', resolve(out, `cap-${vw}x${vh}-${theme}-${density}-s${step}.png`));
          if (step === 100) {
            await openSettings();
            await browser('screenshot', resolve(out, `cap-${vw}x${vh}-${theme}-${density}-s${step}-settings.png`));
          }
        }
      }
    }
  }
  await evaluate(`(() => { localStorage.removeItem('olga-companion.density.v1'); localStorage.removeItem('olga-companion.motion.v1'); localStorage.removeItem('${UI_SCALE_KEY}'); return 'clean'; })()`);
});

// ai-dock-and-neo-fx todo 3: dock message text rides --fs-m and follows the UI scale.
// A probe message (inserted and removed inside one eval, so the timeline guard never sees it)
// reads the real cascade; no chat is sent and nothing is typed.
async function measureDockText() {
  return evaluate(`(() => {
    const dock = document.getElementById('workbench-chat-dock');
    const wrap = document.createElement('div');
    wrap.className = 'msg';
    wrap.style.cssText = 'position:absolute;visibility:hidden';
    wrap.innerHTML = '<div class="bubble assistant"><div class="md"><h3>h</h3><h4>h</h4><p>p</p><code>c</code></div></div><div class="bubble user">u</div>';
    dock.appendChild(wrap);
    const px = (sel, prop) => parseFloat(getComputedStyle(wrap.querySelector(sel))[prop]);
    const out = {
      assistant: px('.bubble.assistant', 'fontSize'), user: px('.bubble.user', 'fontSize'),
      p: px('.md p', 'fontSize'), h3: px('.md h3', 'fontSize'), h4: px('.md h4', 'fontSize'), code: px('.md code', 'fontSize'),
      lineHeight: px('.bubble.assistant', 'lineHeight'),
      composer: (() => { const t = dock.querySelector('.composer textarea'); return t ? parseFloat(getComputedStyle(t).fontSize) : null; })(),
    };
    wrap.remove();
    return out;
  })()`);
}

for (const [step, want] of [[80, 10.4], [100, 13], [130, 16.9]]) {
  test(`dock text at UI scale ${step} %: bubbles and composer read ${want}px, headings never smaller than body`, async () => {
    await openCell(1280, 800, 'ko', 'dark');
    await setStoredScale(step);
    const m = await measureDockText();
    const near = (got, exp) => Math.abs(got - exp) < 0.06;
    assert.ok(near(m.assistant, want), `assistant bubble is ${m.assistant}px (want ${want})`);
    assert.ok(near(m.user, want), `user bubble is ${m.user}px (want ${want})`);
    assert.ok(near(m.p, want), `markdown paragraph is ${m.p}px (want ${want})`);
    assert.ok(near(m.lineHeight, want * 1.5), `bubble line-height is ${m.lineHeight}px (want ${want * 1.5})`);
    assert.ok(m.h3 >= m.assistant && m.h4 >= m.assistant, `headings ${m.h3}/${m.h4}px stay at or above body ${m.assistant}px`);
    assert.ok(near(m.code, 12 * step / 100), `inline code is ${m.code}px (want ${12 * step / 100})`);
    assert.ok(m.composer === null || near(m.composer, want), `composer is ${m.composer}px (want ${want})`);
    if (step === 100) assert.ok(m.code >= 12, 'the 12px floor holds at 100 %');
  });
}

for (const dockW of [300, 560]) {
  test(`dock text at dock ${dockW}: a long assistant message does not clip`, async () => {
    await openCell(1280, 800, 'ko', 'dark');
    await setDockWidth(dockW);
    const clip = await evaluate(`(() => {
      const dock = document.getElementById('workbench-chat-dock');
      const timeline = dock.querySelector('.timeline');
      const wrap = document.createElement('div');
      wrap.className = 'msg';
      wrap.setAttribute('data-probe', 'dock-text');
      wrap.innerHTML = '<div class="bubble assistant"><div class="md"><h3>demo heading</h3><p>' + 'demo_line_export_case ' .repeat(14) + '</p><pre><code>demo_case.genkey ' + 'x'.repeat(48) + '</code></pre></div></div>';
      timeline.appendChild(wrap);
      const bubble = wrap.querySelector('.bubble');
      const r = bubble.getBoundingClientRect(), t = timeline.getBoundingClientRect();
      const res = { bubbleRight: r.right, timelineRight: t.right, overX: bubble.scrollWidth - bubble.clientWidth };
      wrap.remove();
      return res;
    })()`);
    await browser('screenshot', resolve(out, `dock-text-${dockW}.png`));
    assert.ok(clip.bubbleRight <= clip.timelineRight + 1, `bubble right edge ${clip.bubbleRight} stays inside the timeline ${clip.timelineRight}`);
    assert.ok(clip.overX <= 1, `bubble content overflows ${clip.overX}px at dock ${dockW}`);
  });
}

// Sound row (lane lnsound): the row, slider and test button fit and read in
// both locales and themes. Nothing here plays a cue: the test button is only
// measured, never clicked.
for (const [vw, vh] of [[1280, 800], [1000, 700]]) {
  for (const [locale, theme] of [['ko', 'dark'], ['en', 'light']]) {
    test(`sound row at ${vw}x${vh} ${locale}/${theme}: slider and test button show no clipping`, async () => {
      await openCell(vw, vh, locale, theme);
      await evaluate(`(() => { localStorage.setItem('olga-companion.sound.v1', 'quiet'); return 'sound'; })()`);
      await browser('open', appUrl);
      await browser('wait', '#workbench-chat-dock');
      await openSettings();
      const row = await evaluate(`(() => {
        const label = document.getElementById('display-sound-label');
        const range = document.getElementById('display-sound-volume');
        const button = [...document.querySelectorAll('.display-card button')].find((b) => b.textContent.trim() === (${JSON.stringify(locale)} === 'ko' ? '소리 확인' : 'Test sound'));
        const card = document.querySelector('.display-card').getBoundingClientRect();
        const inside = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.left >= card.left - 1 && r.right <= card.right + 1; };
        return {
          label: !!label && inside(label),
          range: !!range && inside(range) && !range.disabled,
          button: !!button && inside(button) && !button.disabled,
          segmented: document.querySelectorAll('[aria-label="${locale === 'ko' ? '소리' : 'Sound'}"] button').length,
        };
      })()`);
      await browser('screenshot', resolve(out, `sound-row-${vw}x${vh}-${locale}-${theme}.png`));
      assert.deepEqual(row, { label: true, range: true, button: true, segmented: 3 }, `sound row at ${vw}x${vh} ${locale}/${theme}`);
      assert.deepEqual(await detectClipping(), [], `sound row clipping at ${vw}x${vh} ${locale}/${theme}`);
    });
  }
}

const RESULTS_SQUEEZE = {
  root: '',
  results: [{
    id: 'demo_run/case.ppl',
    name: 'case.ppl',
    rel: 'demo_run/case.ppl',
    origin: 'run',
    size: 8192,
    suffix: '.ppl',
    modified_ns: 1762000000000000000,
    run_id: 'demo_run',
    run_state: 'completed',
    run_ok: true,
    source_name: LONG_CASE,
    source_sha256: null,
    runtime_kind: 'OPI',
    runtime_version: '2024.1',
    runtime_candidate_id: null,
    output_sha256: 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
    lineage_status: 'receipt_output',
    lineage: { kind: 'run', source_name: LONG_CASE },
  }],
};
const RESULTS_VARS = {
  ok: true,
  variables: [{ index: 0, variable: 'PT', position: 'BR1', unit: 'Pa', description: '' }],
  file_type: 'ppl',
  branches: ['BR1'],
  timesteps: [0],
};
const RESULTS_PROFILE = {
  path: 'demo_run/case.ppl',
  variable: 'PT',
  branch: 'BR1',
  timestep: 0,
  timestep_unit: 's',
  positions: [0, 10],
  values: [101325, 101400],
  unit: 'Pa',
  description: null,
};

async function openResultsWithSelection(vw, vh, locale, theme) {
  await openCell(vw, vh, locale, theme);
  await resetSashStorage();
  await route('/api/workspace/context', { ...contextWithCase, active: { name: LONG_CASE, path: LONG_CASE } });
  await route('/api/workspace/active', { name: LONG_CASE, path: LONG_CASE });
  await route('/api/workspace/results', RESULTS_SQUEEZE);
  await route('/api/results/load', RESULTS_VARS);
  await route('/api/results/profile', RESULTS_PROFILE);
  await browser('open', appUrl);
  await browser('wait', '#workbench-chat-dock');
  await browser('wait', '1500');
  await evaluate(`(() => { document.querySelector('.wb-activity [data-view="results"]')?.click(); return 'results'; })()`);
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const ready = await evaluate(`!!document.querySelector('.rv-view .rv-head .ws-canvas-name')`);
    if (ready) break;
    const picked = await evaluate(`(() => { const b = document.querySelector('.rv-files .ws-file'); if (b && !document.querySelector('.rv-head')) { b.click(); return true; } return false; })()`);
    if (picked) await browser('wait', '800');
    else await browser('wait', '500');
  }
  await browser('wait', '700');
}

async function measureResultsDetail() {
  return evaluate(`(() => {
    const view = document.querySelector('.rv-view');
    const name = document.querySelector('.rv-head .ws-canvas-name');
    const lineage = document.querySelector('.result-lineage');
    const main = document.querySelector('.rv-main');
    const vw = window.innerWidth;
    const pageX = document.documentElement.scrollWidth - vw;
    if (!view || !name || !lineage || !main) return { missing: true, pageX };
    const cs = getComputedStyle(name);
    const lh = parseFloat(cs.lineHeight) || 0;
    const h = name.getBoundingClientRect().height;
    const lines = lh > 0 ? h / lh : 0;
    const cols = getComputedStyle(view).gridTemplateColumns.split(' ').length;
    const nameClip = name.scrollWidth - name.clientWidth;
    const lineageClips = [...lineage.querySelectorAll('span')].map((s) => s.scrollWidth - s.clientWidth);
    const lineageCut = (() => {
      const lr = lineage.getBoundingClientRect(), mr = main.getBoundingClientRect();
      return Math.max(0, lr.right - mr.right, mr.left - lr.left);
    })();
    return { pageX, lines, cols, nameClip, lineageMax: Math.max(0, ...lineageClips), lineageCut, viewW: Math.round(view.getBoundingClientRect().width) };
  })()`);
}

for (const [vw, vh] of [[1280, 800], [1024, 768]]) {
  test(`results detail at ${vw}x${vh}: file name and lineage chips stay readable with explorer+dock open`, async () => {
    await openResultsWithSelection(vw, vh, 'en', 'dark');
    await browser('screenshot', resolve(out, `results-${vw}x${vh}.png`));
    const m = await measureResultsDetail();
    assert.ok(!m.missing, `results detail rendered at ${vw}x${vh} (${JSON.stringify(m)})`);
    assert.ok(m.pageX <= 1, `page scrolls sideways ${m.pageX}px at ${vw}x${vh}`);
    assert.ok(m.lines <= 2.2, `file name wraps ${m.lines.toFixed(1)} lines at ${vw}x${vh} (want <= 2)`);
    assert.ok(m.nameClip <= 1, `file name clips ${m.nameClip}px at ${vw}x${vh}`);
    assert.ok(m.lineageMax <= 1, `a lineage chip clips ${m.lineageMax}px at ${vw}x${vh}`);
    assert.ok(m.lineageCut <= 1, `lineage cut ${m.lineageCut}px by the detail column at ${vw}x${vh}`);
    await route('/api/workspace/context', contextWithCase);
  });
}

// Pipe-table draft card: a mocked chat history carries a draft import (or a refused one) and the
// draft network route; nothing is sent. Invented demo names only.
const DRAFT_ID = 'd'.repeat(32);
const DRAFT_SESSION = 'pipe-draft-session';
const DRAFT_RESULT = {
  created: true, draft_id: DRAFT_ID, revision: 1, source_name: 'demo_network_table.csv', issue_count: 0, issues: [],
  counts: { flowpaths: 5, pipes: 11, junctions: 2, boundaries: 2, valves: 1, sections: 9240 },
  caps: { nodes: { value: 4, limit: 256 }, flowpaths: { value: 5, limit: 512 }, valves: { value: 1, limit: 256 }, sections: { value: 9240, limit: 10000 } },
  section_stats: { shortest_section_m: 0.5, longest_section_m: 1, worst_ratio_in_flowpaths: 1.25 },
  junction_warning_count: 1,
};
const DRAFT_REFUSED = {
  created: false, issue_count: 24, note: 'No draft was made. The table needs these fixes first.',
  issues: [
    { row: 5, field: 'length_m', reason: 'value is missing' },
    { row: 9, field: 'to_node', reason: 'demo_line_02 rows disagree on their from/to nodes' },
    { row: null, field: 'topology', reason: 'the flowpaths do not form one connected network' },
  ],
};
const DRAFT_NETWORK = {
  draft_id: DRAFT_ID, revision: 1, counts: { nodes: 4, flowpaths: 5, edges: 5 }, kinds: ['source', 'junction', 'sink'],
  nodes: [['SRC_001', 0], ['J_001', 1], ['J_002', 1], ['SNK_001', 2]],
  edges: [[0, 1, 'FP_001'], [1, 2, 'FP_002'], [1, 2, 'FP_003'], [2, 3, 'FP_004'], [2, 3, 'FP_005']],
};

async function openDraftChat(vw, vh, locale, theme, result) {
  await openCell(vw, vh, locale, theme);
  const records = [
    { record: 'user', text: 'demo_network_table.csv' },
    { record: 'event', type: 'tool_result', call_id: 'draft-call', name: 'pipe_table_import', result, status: 'completed' },
  ];
  await route('/api/chat/sessions', { sessions: [{ session_id: DRAFT_SESSION, title: 'draft demo', updated_ms: 2 }] });
  await route(`/api/chat/session/${DRAFT_SESSION}`, { records });
  await route(`/api/case-draft/${DRAFT_ID}/topology`, DRAFT_NETWORK);
  await evaluate(`(() => { localStorage.setItem('olga_last_chat_session', '${DRAFT_SESSION}'); return 'session'; })()`);
  await browser('open', appUrl);
  await browser('wait', '#workbench-chat-dock');
  await browser('wait', '.pipe-draft');
  await browser('wait', '800');
  await centre('.pipe-draft');
}

// Centre in the scroll region so the status bar and composer never cover the target.
async function centre(selector) {
  await evaluate(`(() => { document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({ block: 'center' }); return 'centred'; })()`);
  await browser('wait', '200');
}

async function measureDraftCard() {
  return evaluate(`(() => {
    const card = document.querySelector('.pipe-draft');
    const dock = document.getElementById('workbench-chat-dock');
    if (!card || !dock) return null;
    const num = (c) => (c.match(/[\\d.]+/g) || []).map(Number);
    const lin = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    const L = (c) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
    const ratio = (a, b) => (Math.max(L(a), L(b)) + 0.05) / (Math.min(L(a), L(b)) + 0.05);
    const opaqueBg = (start) => { for (let a = start; a; a = a.parentElement) { const c = num(getComputedStyle(a).backgroundColor); if (c.length >= 3 && (c.length === 3 || c[3] >= 0.99)) return c.slice(0, 3); } return [255, 255, 255]; };
    const textRatio = (el) => ratio(num(getComputedStyle(el).color).slice(0, 3), opaqueBg(el));
    const meter = card.querySelector('.pipe-draft-meter');
    const meta = card.querySelector('.pipe-draft-meta');
    const issue = card.querySelector('.pipe-draft-issue-reason');
    const cr = card.getBoundingClientRect();
    const dr = dock.getBoundingClientRect();
    return {
      good: !!card.querySelector('.evidence-outcome.is-good'),
      attention: !!card.querySelector('.evidence-outcome.is-attention'),
      tiles: card.querySelectorAll('.pipe-draft-counts > div').length,
      meters: card.querySelectorAll('.pipe-draft-meter').length,
      issues: card.querySelectorAll('.pipe-draft-issues li').length,
      action: !!card.querySelector('.pipe-draft-action'),
      expanded: card.querySelector('.pipe-draft-action')?.getAttribute('aria-expanded') ?? null,
      cardOverflowX: card.scrollWidth - card.clientWidth,
      rightEdge: Math.round(cr.right - dr.right),
      pageX: document.documentElement.scrollWidth - window.innerWidth,
      metaText: meta ? +textRatio(meta).toFixed(2) : null,
      issueText: issue ? +textRatio(issue).toFixed(2) : null,
      meterEdge: meter ? +ratio(num(getComputedStyle(meter).borderTopColor).slice(0, 3), opaqueBg(meter.parentElement)).toFixed(2) : null,
      meterFill: meter ? +ratio(num(getComputedStyle(meter.firstElementChild).backgroundColor).slice(0, 3), opaqueBg(meter)).toFixed(2) : null,
    };
  })()`);
}

for (const [vw, vh, locale, theme] of [[1024, 768, 'ko', 'dark'], [1024, 768, 'en', 'light'], [1280, 800, 'ko', 'dark'], [1280, 800, 'en', 'light']]) {
  test(`pipe-draft card at ${vw}x${vh} ${locale}/${theme}: counts, caps and statistics fit the dock and Show network opens the map`, async () => {
    await openDraftChat(vw, vh, locale, theme, DRAFT_RESULT);
    const m = await measureDraftCard();
    await browser('screenshot', resolve(out, `pipe-draft-${vw}x${vh}-${locale}-${theme}-card.png`));
    assert.ok(m, 'the draft card and the dock are rendered');
    assert.ok(m.good && !m.attention, 'a draft without issues reads as ready');
    assert.equal(m.tiles, 6, 'six counts');
    assert.equal(m.meters, 4, 'four cap meters');
    assert.ok(m.cardOverflowX <= 1, `card overflows ${m.cardOverflowX}px`);
    assert.ok(m.rightEdge <= 1, `card sticks out of the dock by ${m.rightEdge}px`);
    assert.ok(m.pageX <= 1, `page scrolls sideways ${m.pageX}px`);
    assert.ok(m.metaText >= 4.5, `secondary text holds 4.5:1 (${m.metaText})`);
    assert.ok(m.meterEdge >= 3, `meter edge holds 3:1 (${m.meterEdge})`);
    assert.ok(m.meterFill >= 3, `meter fill holds 3:1 (${m.meterFill})`);
    assert.deepEqual((await detectClipping()).filter((line) => /pipe-draft|evidence/.test(line)), [], 'no clipped text in the card');
    await centre('.pipe-draft-action');
    await browser('click', '.pipe-draft-action');
    for (let attempt = 0; attempt < 20 && (await evaluate(`document.querySelectorAll('.pipe-draft-map .topo-node').length`)) < 4; attempt += 1) await browser('wait', '300');
    await centre('.pipe-draft-map');
    await browser('wait', '500');
    const open = await evaluate(`(() => {
      const map = document.querySelector('.pipe-draft-map');
      const dock = document.getElementById('workbench-chat-dock').getBoundingClientRect();
      const r = map ? map.getBoundingClientRect() : null;
      return {
        nodes: document.querySelectorAll('.pipe-draft-map .topo-node').length,
        expanded: document.querySelector('.pipe-draft-action').getAttribute('aria-expanded'),
        overflowRight: r ? Math.round(r.right - dock.right) : null,
        height: r ? Math.round(r.height) : 0,
        pageX: document.documentElement.scrollWidth - window.innerWidth,
      };
    })()`);
    await browser('screenshot', resolve(out, `pipe-draft-${vw}x${vh}-${locale}-${theme}-network.png`));
    assert.equal(open.expanded, 'true', 'the action reports it is open');
    assert.equal(open.nodes, 4, 'the draft graph draws its four nodes');
    assert.ok(open.overflowRight <= 1, `the map sticks out of the dock by ${open.overflowRight}px`);
    assert.ok(open.height >= 160, `the map stays usable (${open.height}px)`);
    assert.ok(open.pageX <= 1, `page scrolls sideways ${open.pageX}px with the map open`);
  });
}

test('pipe-draft card: an import with issues lists them and shows no ready state, no counts and no network action', async () => {
  await openDraftChat(1280, 800, 'ko', 'dark', DRAFT_REFUSED);
  const m = await measureDraftCard();
  await browser('screenshot', resolve(out, 'pipe-draft-1280x800-ko-dark-issues.png'));
  assert.ok(m.attention && !m.good, 'the card reads as needing fixes, never ready');
  assert.equal(m.issues, 3, 'every returned issue is listed');
  assert.equal(m.tiles, 0, 'no counts without a draft');
  assert.equal(m.meters, 0, 'no size check without a draft');
  assert.ok(!m.action, 'no Show network without a draft');
  assert.ok(m.cardOverflowX <= 1 && m.pageX <= 1, 'the issue list fits the dock');
  assert.ok(m.issueText >= 4.5, `issue text holds 4.5:1 (${m.issueText})`);
  await route('/api/chat/sessions', { sessions: [] });
  await evaluate(`(() => { localStorage.removeItem('olga_last_chat_session'); return 'clean'; })()`);
  await browser('open', appUrl);
  await browser('wait', '#workbench-chat-dock');
});

test('self-allow-list: no approval, no chat, no sends', async () => {
  const end = await snapshotGuard();
  assert.equal(end.approval, 0, 'an approval surface appeared during a read-only run');
  assert.deepEqual(end.timeline, globalThis.__paneSqueezeTimeline, 'chat timeline changed during a read-only run');
});
