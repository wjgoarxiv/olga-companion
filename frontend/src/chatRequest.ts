import type { Locale } from './i18n/index.ts';

export type ChatRequestBody = {
  readonly session_id: string;
  readonly message: string;
  readonly locale: Locale;
};

export function chatRequestBody(sessionId: string, message: string, locale: Locale): ChatRequestBody {
  return { session_id: sessionId, message, locale };
}
