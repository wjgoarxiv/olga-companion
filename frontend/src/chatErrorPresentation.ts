import type { I18nKey } from './i18n/ko.ts';

export type ChatErrorKind =
  | 'bad-request'
  | 'auth'
  | 'rate-limit'
  | 'server'
  | 'offline'
  | 'generic';

export interface DescribedChatError {
  readonly kind: ChatErrorKind;
  readonly titleKey: I18nKey;
  readonly detailsKey: I18nKey;
  readonly raw: string;
}

const TITLE_KEYS: Record<ChatErrorKind, I18nKey> = {
  'bad-request': 'chat.errBadRequest',
  auth: 'chat.errAuth',
  'rate-limit': 'chat.errRateLimit',
  server: 'chat.errServer',
  offline: 'chat.errOffline',
  generic: 'chat.errGeneric',
};

function statusFromPayload(raw: string): number | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const record = parsed as Record<string, unknown>;
      for (const key of ['status', 'status_code', 'code']) {
        const value = record[key];
        if (typeof value === 'number' && Number.isInteger(value)) return value;
      }
    }
  } catch {
    // Not JSON — fall through to text scanning.
  }
  const match = /(?:^|[\s:("'])HTTP\s+(\d{3})|[^.\d](4\d{2}|5\d{2})(?![.\d])/m.exec(raw);
  if (match) {
    const status = Number(match[1] ?? match[2]);
    if (Number.isInteger(status)) return status;
  }
  return null;
}

const SIDECAR_PATTERN = /approv|승인|expir|만료|pending|보류|reject|거부|refus|거절|workspace|작업 ?공간|sidecar|사이드카|token|토큰|claim|dispatch|resume|계속 진행|unit|단위|payload|페이로드|closed|닫혔|unavailable|처리 불가/;

export function describeChatError(raw: string): DescribedChatError {
  const text = raw.toLowerCase();
  const status = statusFromPayload(raw);
  let kind: ChatErrorKind = 'generic';
  if (status === 400 || status === 404 || status === 422) kind = 'bad-request';
  else if (status === 401 || status === 403) kind = 'auth';
  else if (status === 429) kind = 'rate-limit';
  else if (status != null && status >= 500 && status <= 599) kind = 'server';
  else if (
    /\bfailed to fetch\b|\bnetwork ?error\b|\boffline\b|\beconnrefused\b|\bload failed\b|\bnetwork request failed\b/.test(text)
  ) kind = 'offline';
  const providerNamed = /provider|공급자|제공자/.test(raw);
  const detailsKey: I18nKey = kind !== 'generic' || providerNamed
    ? 'chat.errDetails'
    : SIDECAR_PATTERN.test(raw)
      ? 'chat.errSidecarDetails'
      : 'chat.errDetails';
  return { kind, titleKey: TITLE_KEYS[kind], detailsKey, raw };
}
