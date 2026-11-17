import { translate, type I18nKey, type Locale } from './i18n/index.ts';

const OUTCOME_KEYS: Record<string, I18nKey> = {
  saved: 'outcome.saved',
  verified: 'outcome.verified',
  invalid_base_url: 'outcome.invalidBaseUrl',
  not_found: 'outcome.invalidBaseUrl',
  insecure_scheme: 'outcome.insecureScheme',
  missing_model: 'outcome.missingModel',
  missing_key: 'outcome.missingKey',
  invalid_label: 'outcome.invalidLabel',
  unsupported_protocol: 'outcome.unsupportedProtocol',
  unauthorized: 'outcome.unauthorized',
  unreachable: 'outcome.unreachable',
  rate_limited: 'outcome.rateLimited',
  request_rejected: 'outcome.requestRejected',
  unexpected_response: 'outcome.unexpectedResponse',
};

/** Outcome -> short recovery sentence (contract task-20). Never echoes input. */
export function outcomeSentence(outcome: string | null | undefined, locale: Locale = 'ko'): string {
  const key = (typeof outcome === 'string' && OUTCOME_KEYS[outcome]) || 'outcome.fallback';
  return translate(locale, key);
}
