import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

function fakeTarget() {
  const target = { isConnected: true, focused: 0, matches: () => false, focus() { this.focused += 1; } };
  return target;
}

test('idle focus return restores the invoker only when focus was lost', async () => {
  const { scheduleIdleFocusReturn } = await import('../src/focusReturn.mjs');
  const queued = [];
  const schedule = (callback) => { queued.push(callback); return () => {}; };

  const lost = fakeTarget();
  scheduleIdleFocusReturn(lost, schedule, () => null);
  assert.equal(lost.focused, 0, 'never synchronous');
  queued.shift()();
  assert.equal(lost.focused, 1, 'focus lost to nothing returns to the invoker');

  const moved = fakeTarget();
  const elsewhere = { isConnected: true };
  scheduleIdleFocusReturn(moved, schedule, () => elsewhere);
  queued.shift()();
  assert.equal(moved.focused, 0, 'focus the user moved on purpose is not stolen back');

  const detached = fakeTarget();
  detached.isConnected = false;
  scheduleIdleFocusReturn(detached, schedule, () => null);
  queued.shift()();
  assert.equal(detached.focused, 0, 'a detached invoker is skipped');
});

test('CommandPalette, Popover and Menu hand focus back to their invoker', async () => {
  for (const file of ['CommandPalette', 'Popover', 'Menu']) {
    const source = await read(`../src/ui/${file}.tsx`);
    assert.match(source, /scheduleIdleFocusReturn/, `${file} returns focus on close`);
    assert.match(source, /document\.activeElement/, `${file} captures the invoker on open`);
  }
});

test('Popover stays a non-modal dialog without a trap', async () => {
  const source = await read('../src/ui/Popover.tsx');
  assert.doesNotMatch(source, /aria-modal/);
  assert.doesNotMatch(source, /'Tab'/);
});

test('GlossaryTerm toggles on Enter and Space while keeping focus-open', async () => {
  const source = await read('../src/GlossaryTerm.tsx');
  assert.match(source, /event\.key === 'Enter'/);
  assert.match(source, /event\.key === ' '/);
  assert.match(source, /event\.preventDefault\(\)/, 'Space must not scroll the page');
  assert.match(source, /onFocus=\{\(\) => setOpen\(true\)\}/, 'focus still opens the term');
});
