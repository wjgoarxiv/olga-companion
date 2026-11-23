// Pure state helpers for the local CLI panel. Copy lives in i18n; the server sends its own ko/en text.
const SIGN_IN = new Set(['not_logged_in', 'login_expired']);

export function localCliView(status, check) {
  if (!status) return { state: 'loading', titleKey: 'localCli.titleLoading', stepKey: null, showCommand: false };
  if (status.code !== 'ok') return { state: 'not_found', titleKey: null, stepKey: 'localCli.stepInstall', showCommand: false };
  if (!check) return { state: 'found', titleKey: 'localCli.titleFound', stepKey: 'localCli.stepCheck', showCommand: false };
  if (check.code === 'ok') return { state: 'ready', titleKey: 'localCli.titleReady', stepKey: null, showCommand: false };
  if (SIGN_IN.has(check.code)) return { state: 'needs_sign_in', titleKey: null, stepKey: 'localCli.stepSignIn', showCommand: true };
  return { state: 'problem', titleKey: null, stepKey: 'localCli.stepRetry', showCommand: false };
}

export function localCliMessage(result, locale) {
  if (!result) return '';
  return locale === 'en' ? result.message_en : result.message_ko;
}

export function localCliBillingKey(billing) {
  if (billing === 'subscription') return 'localCli.billingSubscription';
  if (billing === 'api_key') return 'localCli.billingApiKey';
  return null;
}
