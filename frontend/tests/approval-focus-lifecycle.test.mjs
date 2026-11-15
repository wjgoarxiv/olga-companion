import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('shared Button forwards an HTML button ref without losing its existing contract', async () => {
  const button = await read('../src/ui/Button.tsx');

  assert.match(button, /forwardRef<HTMLButtonElement, ButtonProps>/);
  assert.match(button, /ref=\{ref\}/);
  assert.match(button, /ButtonHTMLAttributes<HTMLButtonElement>/);
  assert.match(button, /aria-busy=\{busy \|\| undefined\}/);
  assert.match(button, /disabled=\{disabled \|\| busy\}/);
  assert.match(button, /busy \? busyLabel \?\? children : children/);
  assert.match(button, /ui-button-label-measure/);
});

test('active approval focuses its explicit ref after pending clears and never relies on autoFocus', async () => {
  const card = await read('../src/ApprovalCard.tsx');

  assert.doesNotMatch(card, /autoFocus/);
  assert.match(card, /approveButtonRef = useRef<HTMLButtonElement \| null>\(null\)/);
  assert.match(card, /<Button[\s\S]*ref=\{approveButtonRef\}[\s\S]*t\('approval\.approveRun'\)/);
  assert.match(card, /if \(!pending && !resolved[\s\S]*approveButtonRef\.current[\s\S]*\.focus\(\)/);
  assert.match(card, /\}, \[pending, resolved\]\)/, 'the focus effect must rerun when a disabled pending card becomes actionable');
});

test('approval restores only usable prior focus and falls back to enabled chat controls', async () => {
  const card = await read('../src/ApprovalCard.tsx');

  assert.match(card, /function isUsableFocusTarget\(/);
  assert.match(card, /value instanceof HTMLElement/);
  assert.match(card, /value !== document\.body/);
  assert.match(card, /value\.isConnected/);
  assert.match(card, /:disabled/);
  assert.match(card, /aria-disabled/);
  assert.match(card, /value\.tabIndex >= 0/);
  assert.match(card, /document\.activeElement/);
  assert.match(card, /previousFocusRef\.current = isUsableFocusTarget\(active\) \? active : null/);
  assert.match(card, /\[data-testid="chat-input"\]/);
  assert.match(card, /\.chat button/);
  assert.match(card, /function restoreFocus\(\)[\s\S]*previousFocusRef\.current[\s\S]*fallbackFocusTarget\(\)[\s\S]*\.focus\(\)/);
  assert.match(card, /return \(\) => restoreFocus\(\)/, 'unmount restores focus through the same guarded path');
  assert.match(card, /if \(resolved\) restoreFocus\(\)/, 'resolution restores focus without rendering an active dialog');
});

test('resolved approval stays neutral and only the active card is an alertdialog', async () => {
  const card = await read('../src/ApprovalCard.tsx');

  const resolvedStart = card.lastIndexOf('if (resolved)');
  const resolvedBranch = card.slice(resolvedStart, card.indexOf('return (', resolvedStart) + 300);
  assert.match(resolvedBranch, /OperationStatus/);
  assert.match(resolvedBranch, /tone="info"/);
  assert.doesNotMatch(resolvedBranch, /alertdialog|Approval required/);
  assert.match(card, /role="alertdialog" aria-label=\{t\('approval\.title'\)\}/);
});
