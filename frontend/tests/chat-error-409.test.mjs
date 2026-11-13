import assert from 'node:assert/strict';
import test from 'node:test';
import { describeChatError, withoutConflictMarker } from '../src/chatErrorPresentation.ts';

test('the conflict marker strips to the human sentence', () => {
  assert.equal(
    withoutConflictMarker('Workspace context changed; refresh. (HTTP 409 approval_context_changed)'),
    'Workspace context changed; refresh.',
  );
  assert.equal(withoutConflictMarker('plain message'), 'plain message');
  assert.equal(
    withoutConflictMarker('ends with (HTTP 400 x) but no code (HTTP 400)'),
    'ends with (HTTP 400 x) but no code (HTTP 400)',
  );
});

test('conflict display text never shows the marker', () => {
  const raw = 'Workspace context changed; refresh. (HTTP 409 approval_context_changed)';
  const described = describeChatError(raw);
  assert.equal(described.raw, raw);
  assert.equal(described.displayText, 'Workspace context changed; refresh.');
  assert.equal(describeChatError('plain failure').displayText, 'plain failure');
});

// T9c RED: a 409 from the approval execute path must never render the generic
// "response failed before any answer" copy. The server now tags every 409
// with a code, and the row must map it to the conflict kind with precise
// guidance plus the existing retry control.

test('a stale-generation 409 is a conflict, not generic', () => {
  const described = describeChatError(
    'Workspace context changed; refresh the preview and approve again. (HTTP 409 approval_context_changed)',
  );
  assert.notEqual(described.kind, 'generic');
  assert.equal(described.kind, 'conflict');
  assert.equal(described.titleKey, 'chat.errConflictContext');
});

test('an uncertain-dispatch 409 maps to the uncertain conflict copy', () => {
  const described = describeChatError(
    'The approved action outcome could not be confirmed. (HTTP 409 approval_dispatch_uncertain)',
  );
  assert.equal(described.kind, 'conflict');
  assert.equal(described.titleKey, 'chat.errConflictUncertain');
});

test('a rejected-approval 409 maps to the rejected conflict copy', () => {
  const described = describeChatError(
    'This approval was rejected by the user. (HTTP 409 approval_rejected)',
  );
  assert.equal(described.kind, 'conflict');
  assert.equal(described.titleKey, 'chat.errConflictRejected');
});

test('an uncoded 409 still escapes generic with conflict guidance', () => {
  const described = describeChatError('HTTP 409 Conflict');
  assert.equal(described.kind, 'conflict');
  assert.equal(described.titleKey, 'chat.errConflict');
});

test('conflict details keep the sidecar label, not the provider one', () => {
  const described = describeChatError(
    'Workspace context changed; refresh the preview and approve again. (HTTP 409 approval_context_changed)',
  );
  assert.equal(described.detailsKey, 'chat.errSidecarDetails');
});
