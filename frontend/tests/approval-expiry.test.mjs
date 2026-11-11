import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import {
  APPROVAL_EXPIRED_SENTENCE,
  approvalStatusLabel,
  approvalUnavailableResult,
  describeApprovalExpiry,
} from '../src/approvalExpiry.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('a live approval names the local minute it expires', () => {
  const expiresAt = Date.parse('2026-10-23T15:25:53Z') / 1000;
  const described = describeApprovalExpiry(expiresAt, Date.parse('2026-10-23T15:15:53Z'));
  const clock = new Date(expiresAt * 1000);
  const hh = String(clock.getHours()).padStart(2, '0');
  const mm = String(clock.getMinutes()).padStart(2, '0');

  assert.equal(described.expired, false);
  assert.equal(described.line, `이 승인은 ${hh}:${mm}까지 유효합니다`);
});

test('the client clock disables approval only after the deadline', () => {
  const expiresAt = 1_700_000_000;
  assert.equal(describeApprovalExpiry(expiresAt, expiresAt * 1000).expired, false);
  const past = describeApprovalExpiry(expiresAt, expiresAt * 1000 + 1);
  assert.equal(past.expired, true);
  assert.equal(past.line, APPROVAL_EXPIRED_SENTENCE);
  assert.equal(describeApprovalExpiry(undefined, 0).expired, false);
});

test('an unknown expired or used approval is unavailable, not uncertain', () => {
  const result = approvalUnavailableResult(
    'Pending approval is unknown, expired, or already used.',
  );
  assert.deepEqual(result, {
    ok: false,
    code: 'approval_unavailable',
    error: APPROVAL_EXPIRED_SENTENCE,
  });
  assert.equal(approvalStatusLabel('failed', result), '만료됨/처리 불가');
  assert.equal(approvalStatusLabel('uncertain', { code: 'uncertain_publish' }), null);
  assert.equal(approvalUnavailableResult('Dispatch outcome is uncertain.'), null);
});

test('the approval card shows the deadline and the expired refusal', async () => {
  const card = await read('../src/ApprovalCard.tsx');
  const copy = await read('../src/approvalExpiry.mjs');
  const hook = await read('../src/useApprovalContinuation.ts');
  const tool = await read('../src/ToolUnit.tsx');
  const ko = await read('../src/i18n/ko.ts');
  assert.match(copy, /이 승인은 \$\{hh\}:\$\{mm\}까지 유효합니다/);
  assert.match(copy, /승인 시간이 지났습니다\. 다시 요청하세요\./);
  assert.match(card, /describeApprovalExpiry/);
  assert.match(card, /expiry\.expired/);
  assert.match(card, /t\('approval\.expiredTitle'\)/);
  assert.match(card, /t\('approval\.expiredLine'\)/);
  assert.match(card, /t\('approval\.validUntil'/);
  assert.match(ko, /'approval\.expiredTitle': '만료됨\/처리 불가'/);
  assert.match(card, /t\('approval\.resolvedTitle'\)/);
  assert.match(hook, /approvalUnavailableResult/);
  assert.match(tool, /t\('approval\.expiredTitle'\)/);
  assert.match(tool, /lifecycleLabelKey/);
});
