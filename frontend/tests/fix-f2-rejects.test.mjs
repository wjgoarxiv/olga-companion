import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

// F2 items 1, 2, 3, 5, 7, written RED-first (failed on the pre-fix tree).

test('F2-1: flowpath keyboard focus keeps a visible 2px outline, never outline:none', async () => {
  // Given: the flowpath studio and toolbar styles.
  const css = await read('../src/styles/flowpath-inspector.css');

  // When: a keyboard user tabs to the back control or a toolbar control.
  // Then: the focus-visible treatment draws the shared focus ring.
  assert.match(css, /\.flowpath-back:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--focus\)/s);
  assert.match(css, /\.flowpath-toolbar button:focus-visible[^{]*\{[^}]*outline:\s*2px solid var\(--focus\)/s);
  assert.match(css, /\.flowpath-toolbar select:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--focus\)/s);
  assert.doesNotMatch(css, /:focus-visible\s*\{[^}]*outline:\s*none/s);
});

test('F2-2: result lineage label comes from the results dictionary, unsplit', async () => {
  // Given: the results layout and both dictionaries.
  const [layout, en, ko] = await Promise.all([
    read('../src/ResultsLayout.tsx'),
    read('../src/i18n/en.ts'),
    read('../src/i18n/ko.ts'),
  ]);

  // When: a screen reader names the lineage row (either locale).
  // Then: the label is one dictionary key, not a split English literal.
  assert.doesNotMatch(layout, /'Result proven'\s*\+\s*'ance'/);
  assert.doesNotMatch(layout, /Result provenance/);
  assert.match(layout, /aria-label=\{t\('results\.lineageLabel'\)\}/);
  assert.match(en, /'results\.lineageLabel': 'Result lineage'/);
  const koValue = ko.match(/'results\.lineageLabel': '([^']+)'/);
  assert.ok(koValue && koValue[1].length > 0, 'ko lineage label is non-empty');
  assert.equal(koValue[1], '결과 출처');
});

test('F2-3: sub-44px pointer targets expose a 44px hit area', async () => {
  // Given: the sweep, chat-tools and flowpath styles.
  const [run, tools, flowpath] = await Promise.all([
    read('../src/styles/run.css'),
    read('../src/styles/chat-tools.css'),
    read('../src/styles/flowpath-inspector.css'),
  ]);

  // When: a pointer user taps the sweep chip remove control (19px visual).
  // Then: an ::after expansion carries the hit area to at least 44px.
  assert.match(run, /\.sweep-value-chip button\s*\{[^}]*position:\s*relative/s);
  assert.match(run, /\.sweep-value-chip button::after\s*\{[^}]*inset:\s*-13px/s);

  // When: a pointer user taps the queued-message remove control (28px visual).
  // Then: an ::after expansion carries the hit area to 44px.
  assert.match(tools, /\.queued-message-remove\s*\{[^}]*position:\s*relative/s);
  assert.match(tools, /\.queued-message-remove::after\s*\{[^}]*inset:\s*-8px/s);

  // When: a pointer user taps a flowpath toolbar control (30px visual).
  // Then: the controls themselves are 44px tall (selects admit no ::after).
  assert.match(flowpath, /\.flowpath-toolbar button, \.flowpath-toolbar select\s*\{[^}]*min-height:\s*44px/s);

  // When: a pointer user taps a sweep range/add input (36px visual).
  // Then: the inputs themselves are 44px tall.
  assert.match(run, /\.sweep-range-grid input, \.sweep-value-add input\s*\{[^}]*height:\s*44px/s);
  assert.doesNotMatch(run, /\.sweep-range-grid input, \.sweep-value-add input\s*\{[^}]*height:\s*36px/s);
});

test('F2-5: an externally updated queued message resyncs the edit draft', async () => {
  // Given: the queued-message row.
  const queued = await read('../src/QueuedMessages.tsx');

  // When: the parent hands the row a changed item.message after mount.
  // Then: the draft follows the new message instead of keeping stale text.
  assert.match(queued, /useEffect/);
  assert.match(queued, /setDraft\(item\.message\)/);
});

test('F2-7: icon-only regions expose assistive-technology names and keyboard scroll', async () => {
  // Given: the chat header and the run console panel.
  const [chat, consolePanel] = await Promise.all([
    read('../src/ChatView.tsx'),
    read('../src/RunConsolePanel.tsx'),
  ]);

  // When: assistive tech names the header action group.
  // Then: the labelled div carries a group role so the name is exposed.
  assert.match(chat, /<div className="chat-head-actions" role="group"/);

  // When: a keyboard user reaches the run log.
  // Then: the labelled <pre> is a tab stop so it can be scrolled.
  assert.match(consolePanel, /<pre className="run-console-tail" tabIndex=\{0\}/);
});
