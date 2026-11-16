import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

// v0.1.4 todo 9: fixes for the independent review of the 0.1.4 UX diff.
// Pure logic runs against .mjs/.ts modules; the React wiring that has no DOM
// harness is pinned as source text, like the neighbouring v014 tests.
const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

/* ---------- 1. inert cover: focus rescue + nodes swapped in later ---------- */

function fakeShell(initial) {
  const events = [];
  const nodes = new Set(initial);
  const doc = {
    activeElement: null,
    querySelectorAll: () => Array.from(nodes),
  };
  let onChange = null;
  let stopped = false;
  return {
    events,
    nodes,
    doc,
    watch: (callback) => {
      onChange = callback;
      return () => { stopped = true; onChange = null; };
    },
    fire: () => onChange?.(),
    isStopped: () => stopped,
  };
}

function fakeNode(name, shell) {
  let inert = false;
  return {
    name,
    contained: new Set(),
    contains(other) { return other === this || this.contained.has(other); },
    get inert() { return inert; },
    set inert(value) { inert = value; shell.events.push(`${name}.inert=${value}`); },
  };
}

test('inert cover: focus inside a covered node is moved out before the node goes inert', async () => {
  const { applyInertCover } = await import('../src/shell/inertCover.mjs');
  const shell = fakeShell([]);
  const centre = fakeNode('centre', shell);
  const field = {};
  centre.contained.add(field);
  shell.nodes.add(centre);
  shell.doc.activeElement = field;
  applyInertCover({
    doc: shell.doc,
    selectors: ['.shell-main'],
    rescueFocus: () => shell.events.push('rescue'),
    watch: shell.watch,
  });
  assert.deepEqual(shell.events, ['rescue', 'centre.inert=true'], 'focus is rescued first, then the node is inert');
});

test('inert cover: focus outside the covered nodes is left alone', async () => {
  const { applyInertCover } = await import('../src/shell/inertCover.mjs');
  const shell = fakeShell([]);
  const centre = fakeNode('centre', shell);
  shell.nodes.add(centre);
  shell.doc.activeElement = {};
  applyInertCover({ doc: shell.doc, selectors: ['.shell-main'], rescueFocus: () => shell.events.push('rescue'), watch: shell.watch });
  assert.deepEqual(shell.events, ['centre.inert=true']);
});

test('inert cover: a covered node swapped in later (bottom panel toggle) is made inert too', async () => {
  const { applyInertCover } = await import('../src/shell/inertCover.mjs');
  const shell = fakeShell([]);
  const centre = fakeNode('centre', shell);
  const shut = fakeNode('shut', shell);
  shell.nodes.add(centre);
  shell.nodes.add(shut);
  applyInertCover({ doc: shell.doc, selectors: ['.shell-main'], rescueFocus: () => undefined, watch: shell.watch });
  // BottomPanel opens: the shut strip is replaced by the real panel.
  shell.nodes.delete(shut);
  const panel = fakeNode('panel', shell);
  shell.nodes.add(panel);
  shell.fire();
  assert.equal(panel.inert, true, 'the new panel node is inert');
  assert.equal(centre.inert, true);
  assert.equal(shell.events.filter((event) => event === 'centre.inert=true').length, 1, 'already-inert nodes are not touched twice');
});

test('inert cover: focus sitting in a node that appears later is rescued as well', async () => {
  const { applyInertCover } = await import('../src/shell/inertCover.mjs');
  const shell = fakeShell([]);
  applyInertCover({ doc: shell.doc, selectors: ['.wb-panel'], rescueFocus: () => shell.events.push('rescue'), watch: shell.watch });
  const panel = fakeNode('panel', shell);
  const button = {};
  panel.contained.add(button);
  shell.nodes.add(panel);
  shell.doc.activeElement = button;
  shell.fire();
  assert.deepEqual(shell.events, ['rescue', 'panel.inert=true']);
});

test('inert cover: release clears inert on everything it set, stops watching, and spares what was inert already', async () => {
  const { applyInertCover } = await import('../src/shell/inertCover.mjs');
  const shell = fakeShell([]);
  const centre = fakeNode('centre', shell);
  const owned = fakeNode('owned', shell);
  owned.inert = true;
  shell.nodes.add(centre);
  shell.nodes.add(owned);
  shell.events.length = 0;
  const release = applyInertCover({ doc: shell.doc, selectors: ['.shell-main'], rescueFocus: () => undefined, watch: shell.watch });
  const late = fakeNode('late', shell);
  shell.nodes.add(late);
  shell.fire();
  release();
  assert.equal(centre.inert, false);
  assert.equal(late.inert, false, 'a node covered after activation is released too');
  assert.equal(owned.inert, true, 'a node some other code made inert is not ours to release');
  assert.equal(shell.isStopped(), true, 'the watcher is disconnected');
});

test('overlay scrim hands the cover to the shared helper, watches the shell and rescues focus to a toggle', async () => {
  const scrim = await read('../src/shell/OverlayScrim.tsx');
  assert.match(scrim, /applyInertCover\(/, 'the effect delegates to the tested helper');
  assert.match(scrim, /new MutationObserver\(/, 'the shell is watched for swapped covered nodes');
  assert.match(scrim, /childList/, 'child swaps are observed');
  assert.match(scrim, /rescueFocus/, 'focus inside a covered node is moved');
  assert.match(scrim, /\[\s*active\s*\]/, 'the effect follows whether the scrim is active');
  assert.ok(scrim.indexOf('applyInertCover(') < scrim.indexOf('if (!active) return null'), 'the effect precedes the early return (hook order)');
});

/* ---------- 2. layout: narrow-band exclusivity is derived, never persisted ---------- */

const intent = (dockOpen, explorerOpen) => ({
  view: 'workspace', tabs: ['workspace'], dockOpen, explorerOpen, panelOpen: true, panelTab: 'problems',
});

test('layout: the band shows one drawer but the stored intent keeps both', async () => {
  const { effectiveOverlay } = await import('../src/shell/useWorkbenchLayout.ts');
  const state = { intent: intent(true, true), band: null };
  assert.deepEqual(effectiveOverlay(state, true), { dockOpen: true, explorerOpen: false }, 'band: dock wins');
  assert.deepEqual(effectiveOverlay(state, false), { dockOpen: true, explorerOpen: true }, 'widening restores both');
  assert.equal(state.intent.explorerOpen, true, 'the intent object was not rewritten');
});

test('layout: opening the explorer in the band hides the dock without forgetting it', async () => {
  const { chooseOverlay, effectiveOverlay } = await import('../src/shell/useWorkbenchLayout.ts');
  const start = { intent: intent(true, true), band: null };
  const next = chooseOverlay(start, 'explorer', true, true);
  assert.deepEqual(effectiveOverlay(next, true), { dockOpen: false, explorerOpen: true });
  assert.equal(next.intent.dockOpen, true, 'the dock choice survives in the intent');
  assert.deepEqual(effectiveOverlay(next, false), { dockOpen: true, explorerOpen: true }, 'widening past 1024 restores both');
});

test('layout: closing the visible drawer in the band never reveals the hidden one', async () => {
  const { chooseOverlay, effectiveOverlay } = await import('../src/shell/useWorkbenchLayout.ts');
  const start = { intent: intent(true, true), band: null };
  const next = chooseOverlay(start, 'dock', false, true);
  assert.deepEqual(effectiveOverlay(next, true), { dockOpen: false, explorerOpen: false });
  assert.equal(next.intent.dockOpen, false, 'the explicit close is the new intent');
  assert.equal(next.intent.explorerOpen, true, 'the untouched drawer keeps its intent');
});

test('layout: outside the band the two drawers stay independent and clear any band view', async () => {
  const { chooseOverlay, effectiveOverlay } = await import('../src/shell/useWorkbenchLayout.ts');
  const state = { intent: intent(true, true), band: { dockOpen: true, explorerOpen: false } };
  const next = chooseOverlay(state, 'dock', false, false);
  assert.equal(next.band, null);
  assert.deepEqual(effectiveOverlay(next, false), { dockOpen: false, explorerOpen: true });
});

test('layout: a pending approval opening the dock shows it once the window is wide again', async () => {
  const { chooseOverlay, effectiveOverlay } = await import('../src/shell/useWorkbenchLayout.ts');
  const closedDock = { intent: intent(false, true), band: null };
  const inBand = chooseOverlay(closedDock, 'dock', true, true);
  assert.deepEqual(effectiveOverlay(inBand, true), { dockOpen: true, explorerOpen: false });
  assert.deepEqual(effectiveOverlay(inBand, false), { dockOpen: true, explorerOpen: true }, 'wide: the dock is open and the explorer returns');
  const wide = chooseOverlay(closedDock, 'dock', true, false);
  assert.deepEqual(effectiveOverlay(wide, false), { dockOpen: true, explorerOpen: true });
});

test('layout hook persists the intent, renders the derived flags and re-derives on band changes', async () => {
  const store = await read('../src/shell/useWorkbenchLayout.ts');
  assert.match(store, /saveWorkbenchLayout\(next\)/, 'every other store write goes through the save');
  assert.doesNotMatch(store, /useState<[^>]*>\(\(\) => exclusiveFor\(loadWorkbenchLayout/, 'first load no longer bakes the band choice into the stored layout');
  assert.match(store, /chooseOverlay\(current,\s*changed,/, 'one store write applies the intent rule');
  assert.match(store, /setDockOpen = useCallback\([^\n]*choose\('dock'/, 'setDockOpen routes through it');
  assert.match(store, /setExplorerOpen = useCallback\([^\n]*choose\('explorer'/, 'setExplorerOpen routes through it');
  assert.match(store, /saveWorkbenchLayout\(next\.intent\)/, 'only the intent is persisted by a drawer choice');
  assert.match(store, /effectiveOverlay\(/, 'the layout handed to the shell is derived');
  assert.match(store, /OVERLAY_BAND_QUERY[\s\S]{0,500}addEventListener\('change'/, 'the band is watched live');
});

/* ---------- 3. tutorial end card: focus after the main-focus frame, Esc is its own ---------- */

test('tutorial end card focuses itself in its own frame and keeps Escape to itself', async () => {
  const host = await read('../src/TutorialHost.tsx');
  const start = host.indexOf('function TutorialEndCard');
  const card = host.slice(start, host.indexOf('export default function TutorialHost'));
  assert.match(card, /requestAnimationFrame\(\(\)\s*=>\s*\{?[^]*?cardRef\.current\?\.focus/, 'the focus runs in a requestAnimationFrame so selectView\'s main focus cannot win');
  assert.match(card, /cancelAnimationFrame\(/, 'an unmounted card cancels the pending focus');
  const escapeAt = card.indexOf("'Escape'");
  assert.ok(escapeAt >= 0, 'the card handles Escape');
  assert.match(card.slice(escapeAt, escapeAt + 200), /event\.stopPropagation\(\)/, 'Esc on the card does not also reach useOverlayPanels');
});

/* ---------- 4. 409 recovery comes from the code, not from the status kind ---------- */

test('chat error: recovery follows the approval code even when the status reads as a server error', async () => {
  const { describeChatError } = await import('../src/chatErrorPresentation.ts');
  const uncertain = describeChatError('Gave up after 500 ms waiting. approval_dispatch_uncertain');
  assert.equal(uncertain.recovery, 'open-history', 'an uncertain dispatch never offers a retry');
  assert.notEqual(uncertain.kind, 'conflict', 'the kind stays derived from the status');
  const changed = describeChatError('Gave up after 500 ms waiting. approval_context_changed');
  assert.equal(changed.recovery, 'ask-again');
  assert.equal(describeChatError('Gave up after 500 ms waiting.').recovery, 'retry', 'plain failures keep Retry');
  assert.equal(describeChatError('This approval was rejected. (HTTP 409 approval_rejected)').recovery, 'retry');
});

/* ---------- 5. glossary term keyboard ---------- */

test('glossary term: Enter and Space open without closing, Escape closes', async () => {
  const component = await read('../src/GlossaryTerm.tsx');
  const start = component.indexOf('onKeyDown');
  assert.ok(start >= 0, 'the trigger has a key handler');
  const handler = component.slice(start, component.indexOf('{children}', start));
  assert.match(handler, /event\.key === 'Escape'\)\s*setOpen\(false\)/, 'Escape closes');
  assert.match(handler, /event\.key === 'Enter' \|\| event\.key === ' '\)\s*\{[^}]*event\.preventDefault\(\);\s*setOpen\(true\);/, 'Enter and Space open (idempotent) and do not scroll the page');
  assert.doesNotMatch(handler, /setOpen\(\(value\)\s*=>\s*!value\)/, 'the key path never toggles an already-open popover closed');
});

/* ---------- 6. Korean copy: one word for the workspace ---------- */

test('ko: no bare "작업 폴더" where the workspace is meant', async () => {
  const { ko } = await import('../src/i18n/ko.ts');
  assert.match(ko['chat.errConflictContext'], /작업 공간/);
  assert.doesNotMatch(ko['chat.errConflictContext'], /작업 폴더/);
  assert.match(ko['tutorial.done.body'], /작업 공간 폴더/);
  assert.doesNotMatch(ko['tutorial.done.body'], /작업 폴더/);
});

/* ---------- 7. Open run history reveals the workspace view in the band ---------- */

test('reveal: opening a centre view from the dock closes the dock only in the overlay band', async () => {
  const { revealCentreView } = await import('../src/shell/overlayExclusive.mjs');
  const calls = [];
  const deps = (inBand) => ({ inBand, closeDock: () => calls.push('close'), selectView: (view) => calls.push(view) });
  revealCentreView(deps(true), 'workspace');
  assert.deepEqual(calls, ['close', 'workspace'], 'band: the dock closes first');
  calls.length = 0;
  revealCentreView(deps(false), 'workspace');
  assert.deepEqual(calls, ['workspace'], 'docked or stacked: the dock stays');
});

test('the dock routes its workspace button through the reveal rule', async () => {
  const dock = await read('../src/shell/ChatDockView.tsx');
  assert.match(dock, /revealCentreView\(/, 'ChatDockView uses the rule');
  assert.match(dock, /onOpenWorkspace=\{[^}]*revealCentreView/, 'the chat view workspace button goes through it');
  assert.match(dock, /onToggle\(false\)/, 'the rule closes this dock');
});
