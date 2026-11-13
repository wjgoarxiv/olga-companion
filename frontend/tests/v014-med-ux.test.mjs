import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

// v0.1.4 todo 8: MED items from the v0.1.3 UX audit that reproduced
// (M-06, M-07, M-23/M-24/M-08, M-26, M-31). Source-text assertions in the
// style of motion-tokens.test.mjs; design-contract.md applies (radius 0,
// no shadows, weights up to 600, nothing below 12px).
const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const strip = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');

/** Body of the first rule whose whole selector is `selector` (a descendant like
 *  ".a .selector" does not count), searching `css`, which may be a sliced
 *  at-rule body. Null when absent. */
function ruleBody(css, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`(?:^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`).exec(css);
  return match ? match[1] : null;
}

/** Inner text of the first at-rule block whose prelude starts with `prelude`. */
function atRuleBody(css, prelude) {
  const start = css.indexOf(prelude);
  assert.ok(start >= 0, `${prelude} block exists`);
  const open = css.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    if (css[i] === '}') {
      depth -= 1;
      if (depth === 0) return css.slice(open + 1, i);
    }
  }
  throw new Error(`unbalanced ${prelude}`);
}

test('M-06: history rows wrap the timestamp meta onto its own ellipsized line and never scroll sideways', async () => {
  const css = strip(await read('../src/styles/session-rail.css'));
  const item = ruleBody(css, '.session-item');
  assert.ok(item, '.session-item rule exists');
  assert.match(item, /flex-wrap:\s*wrap/, 'the row may wrap its meta below the title');
  const id = ruleBody(css, '.session-id');
  assert.ok(id, '.session-id rule exists');
  assert.doesNotMatch(id, /flex:\s*0\s+0\s+auto/, 'the meta is no longer a fixed-width nowrap block');
  assert.match(id, /flex:\s*1\s+1\s+100%/, 'the meta takes its own line');
  assert.match(id, /min-width:\s*0/, 'the meta may shrink below its content');
  assert.match(id, /overflow:\s*hidden/, 'the meta clips instead of shearing');
  assert.match(id, /text-overflow:\s*ellipsis/, 'the clip is an ellipsis');
  const list = ruleBody(css, '.session-list');
  assert.ok(list, '.session-list rule exists');
  assert.match(list, /overflow-x:\s*hidden/, 'the history list never shows a horizontal scrollbar');
});

test('M-07: below 900px the results pane has a single scroller (.rv-view); the file list does not nest one', async () => {
  const css = strip(await read('../src/styles/results.css'));
  const narrow = atRuleBody(css, '@container (max-width: 900px)');
  assert.match(ruleBody(narrow, '.rv-view') ?? '', /overflow-y:\s*auto/, '.rv-view stays the scroller when stacked');
  const files = ruleBody(narrow, '.rv-files');
  assert.ok(files, 'stacked layout restyles .rv-files');
  assert.match(files, /max-height:\s*none/, 'the stacked file list is not height-capped');
  assert.match(files, /overflow-y:\s*visible/, 'the stacked file list does not scroll inside the scroller');
  // The phone layout keeps its two fixed panes (34vh list row + detail), so the
  // list must stay its own scroller there.
  const phone = atRuleBody(css, '@media (max-width: 760px)');
  const phoneFiles = ruleBody(phone, '.rv-files');
  assert.ok(phoneFiles, 'phone layout restyles .rv-files');
  assert.match(phoneFiles, /overflow-y:\s*auto/, 'phone file list keeps its own scroll in the fixed row');
  assert.match(phoneFiles, /max-height:\s*260px/, 'phone file list keeps its 260px cap');
});

test('M-23/M-24/M-08: the settings column keeps its 1040px measure and is centred in wide panes', async () => {
  const css = strip(await read('../src/styles/settings.css'));
  const view = ruleBody(css, '.settings-view');
  assert.ok(view, '.settings-view rule exists');
  assert.match(view, /max-width:\s*1040px/, 'the measure is unchanged');
  assert.match(view, /margin-inline:\s*auto/, 'the column centres instead of pinning left');
});

test('M-26: an open overlay drawer makes the covered centre and bottom panel inert, and restores them', async () => {
  const src = await read('../src/shell/OverlayScrim.tsx');
  const cover = await read('../src/shell/inertCover.mjs');
  assert.match(cover, /\.inert\s*=\s*true/, 'covered regions are set inert while the scrim renders');
  assert.match(cover, /\.inert\s*=\s*false/, 'cleanup restores them');
  assert.match(src, /\.shell-main/, 'the centre region is covered');
  assert.match(src, /\.wb-panel\b/, 'the bottom panel is covered');
  const setAt = cover.indexOf('.inert = true');
  const restoreAt = cover.indexOf('.inert = false');
  assert.ok(setAt >= 0 && restoreAt > setAt, 'inert is set, then restored by the release (unmount also restores)');
  assert.ok(/const release = \(\) => \{[^]*?\.inert\s*=\s*false/.test(cover), 'the restore sits in the returned release');
  assert.match(src, /return applyInertCover\(/, 'the effect returns the release as its cleanup');
  const earlyReturn = src.indexOf('if (!active) return null');
  assert.ok(earlyReturn > src.indexOf('applyInertCover('), 'the effect runs before the conditional return (hook order)');
  assert.match(src, /\[\s*active\s*\]/, 'the effect follows whether the scrim is active');
  assert.match(src, /OVERLAY_BAND\s*=\s*'\(min-width: 769px\) and \(max-width: 1023px\)'/, 'band gate unchanged');
});

test('M-31: the runtime popover shows the reason a capability is limited', async () => {
  const bar = await read('../src/shell/StatusBar.tsx');
  assert.match(
    bar,
    /!cap\.enabled\s*&&\s*cap\.reason\s*&&\s*<small className="capability-reason">\{cap\.reason\}<\/small>/,
    'a gated capability renders its reason inside its own li',
  );
  const css = strip(await read('../src/styles/statusbar.css'));
  const row = ruleBody(css, '.wb-status-caps .capability');
  assert.ok(row, 'capability row rule exists');
  assert.match(row, /flex-wrap:\s*wrap/, 'the row wraps so the reason drops under name and state');
  const reason = ruleBody(css, '.wb-status-caps .capability-reason');
  assert.ok(reason, 'the reason has its own rule');
  assert.match(reason, /flex:\s*1\s+1\s+100%/, 'the reason takes the full second line');
  assert.match(reason, /color:\s*var\(--mute\)/, 'the reason is secondary text');
  assert.match(reason, /font-size:\s*var\(--fs-xs\)/, 'the reason uses a token size (not below 12px)');
  assert.doesNotMatch(reason, /box-shadow|border-radius:\s*[1-9]|font-weight:\s*(?:[7-9]\d\d|bold)/, 'radius 0, no shadow, weight up to 600');
});
