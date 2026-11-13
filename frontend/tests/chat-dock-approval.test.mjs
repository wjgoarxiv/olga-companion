import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

import { describeChatError } from '../src/chatErrorPresentation.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

const readCss = async () => {
  const root = await read('../src/styles.css');
  const imports = [...root.matchAll(/@import ['"](.+)['"];/g)];
  const imported = await Promise.all(imports.map((match) => read(`../src/${match[1]}`)));
  return [root, ...imported].join('\n');
};

/* Todo 11: when the dock is collapsed and an approval arrives, the dock opens
 * and focus moves to the card. The controller already surfaces the pending
 * approval; the shell must react to it. */

test('collapsed dock opens when an approval arrives, and the card takes focus', async () => {
  const [app, card] = await Promise.all([
    read('../src/App.tsx'),
    read('../src/ApprovalCard.tsx'),
  ]);
  assert.match(app, /chat\.pendingApproval/, 'the shell watches the pending approval');
  assert.match(app, /pendingApproval[\s\S]*?setDockOpen\(true\)/s, 'an arrival opens the dock');
  assert.match(card, /approveButtonRef\.current[\s\S]*?\.focus\(\)/, 'the card moves focus to its explicit button');
});

/* Todo 11: a wide markdown table must scroll inside its own wrapper instead of
 * stretching the assistant bubble past the timeline. */

test('wide assistant content cannot stretch the timeline', async () => {
  const css = await readCss();
  assert.match(css, /\.msg > \.bubble\s*\{[^}]*min-width:\s*0/s, 'the bubble yields inside the message row');
  assert.match(css, /\.md-table-wrap\s*\{[^}]*max-width:\s*100%/s, 'the table wrapper stays inside the bubble');
  assert.match(css, /\.md-table-wrap\s*\{[^}]*overflow-x:\s*auto/s, 'wide tables scroll in place');
  assert.match(css, /\.md th,[^}]*overflow-wrap:\s*normal/s, 'cells keep their natural width instead of collapsing');
});

/* Todo 11: provider failures read as one short human sentence; the raw
 * provider payload hides behind a details disclosure, never inline. */

const BAD_REQUEST_400 = 'Request failed: HTTP 400 {"detail":[{"loc":["body","message"],"msg":"Field required","type":"missing"}]}';

test('provider failures read as a short human sentence, raw payload disclosed', async () => {
  const described = describeChatError(BAD_REQUEST_400);
  assert.equal(described.kind, 'bad-request');
  assert.equal(described.titleKey, 'chat.errBadRequest');
  assert.equal(described.raw, BAD_REQUEST_400);
  assert.doesNotMatch(described.titleKey, /\{/);
  assert.equal(describeChatError('HTTP 401 Unauthorized').kind, 'auth');
  assert.equal(describeChatError('HTTP 429 slow down').kind, 'rate-limit');
  assert.equal(describeChatError('HTTP 503 upstream').kind, 'server');
  assert.equal(describeChatError('something odd happened').kind, 'generic');

  const view = await read('../src/ChatView.tsx');
  assert.match(view, /describeChatError/, 'the error row is humanised at render');
  assert.match(view, /<details/, 'the raw payload hides behind a disclosure');
  assert.match(view, /detailsKey/, 'the disclosure keeps its label');
  assert.doesNotMatch(view, /detail=\{item\.text\}/, 'raw provider text never renders inline');
  const tools = await read('../src/styles/chat-tools.css');
  assert.match(tools, /\.chat-error-detail summary::[a-z-]+/, 'the disclosure has a visible marker');
  assert.match(tools, /\.chat-error-detail summary\s*\{[^}]*text-decoration:\s*underline/s, 'the disclosure reads as a control');
});

/* Todo 11: approval motion is purely visual — slide-in, draining countdown,
 * approve wipe + stamp, reject collapse — all gated by data-motion. */

test('approval motion is purely visual and motion-gated', async () => {
  const [card, css] = await Promise.all([
    read('../src/ApprovalCard.tsx'),
    readCss(),
  ]);
  assert.match(card, /onApprove\(request\)/, 'approve still calls through synchronously');
  assert.match(card, /approval-countdown/, 'the valid-until line carries a draining bar');
  assert.doesNotMatch(card, /setTimeout\(.*approve|approve.*setTimeout/s, 'no timer gates the approval request');
  assert.match(css, /html\[data-motion="full"\] \.approval-card\s*\{[^}]*animation:/s, 'the card slides in on Full only');
  assert.match(css, /@keyframes approval-in/, 'slide-in curve exists');
  assert.match(css, /approval-stamp/, 'the approved stamp exists');
  assert.match(css, /html\[data-motion="full"\][\s\S]*?grid-template-rows:\s*1fr/s, 'reject collapses the card on Full');
  assert.match(css, /html\[data-motion="subtle"\][\s\S]*?\.approval-card[\s\S]*?animation:\s*none/s, 'Subtle cancels approval motion');
});

/* Todo 11: the simulation guide collapses after the first message and can be
 * reopened from the command palette. */

test('simulation guide reopens from the palette after auto-collapse', async () => {
  const [commands, dispatch, guide, ko, en] = await Promise.all([
    read('../src/shell/commands.ts'),
    read('../src/shell/useWorkbenchCommands.ts'),
    read('../src/SimulationGuide.tsx'),
    read('../src/i18n/ko.ts'),
    read('../src/i18n/en.ts'),
  ]);
  assert.match(commands, /id: 'show-guide'/, 'the palette lists the guide');
  assert.ok(ko.includes("'shell.cmdShowGuide':"), 'ko label exists');
  assert.ok(en.includes("'shell.cmdShowGuide':"), 'en twin exists');
  assert.match(dispatch, /show-guide/, 'the command dispatches');
  assert.match(dispatch, /setDockOpen\(true\)/, 'reopening lands in the open dock');
  assert.match(guide, /olga:open-simulation-guide/, 'the guide listens for the palette event');
});

/* A stale approval card retires with the localized workspace-changed line,
 * and conflict rows show the human sentence without the routing marker. */

test('stale cards and conflict rows never show the routing marker', async () => {
  const [card, continuation, view] = await Promise.all([
    read('../src/ApprovalCard.tsx'),
    read('../src/useApprovalContinuation.ts'),
    read('../src/ChatView.tsx'),
  ]);
  assert.match(
    card,
    /resolved && lifecycle === 'failed' && detail && resolution !== 'context-expired'/,
    'the context-expired resolution renders before the raw failure detail',
  );
  assert.match(continuation, /withoutConflictMarker\(message\)/, 'the card keeps the clean sentence');
  assert.match(view, /described\.displayText/, 'the error row shows the clean sentence');
});
