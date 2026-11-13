export const APPROVAL_EXPIRED_SENTENCE = '승인 시간이 지났습니다. 다시 요청하세요.';

export function describeApprovalExpiry(expiresAt, nowMs) {
  if (typeof expiresAt !== 'number' || !Number.isFinite(expiresAt)) {
    return { expired: false, line: '', time: '' };
  }
  if (nowMs > expiresAt * 1000) {
    return { expired: true, line: APPROVAL_EXPIRED_SENTENCE, time: '' };
  }
  const clock = new Date(expiresAt * 1000);
  const hh = String(clock.getHours()).padStart(2, '0');
  const mm = String(clock.getMinutes()).padStart(2, '0');
  return { expired: false, line: `이 승인은 ${hh}:${mm}까지 유효합니다`, time: `${hh}:${mm}` };
}

export function approvalUnavailableResult(message) {
  if (typeof message !== 'string') return null;
  const used = message.includes('unknown, expired, or already used');
  const closed = message === APPROVAL_EXPIRED_SENTENCE || message.includes(APPROVAL_EXPIRED_SENTENCE);
  if (!used && !closed) return null;
  return { ok: false, code: 'approval_unavailable', error: APPROVAL_EXPIRED_SENTENCE };
}

export function approvalStatusLabel(status, result) {
  if (result && result.code === 'approval_unavailable') return '만료됨/처리 불가';
  return null;
}
