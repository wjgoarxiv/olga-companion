import { translate } from './i18n/index.ts';

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

// One validation issue as a plain sentence: the localized reason for its code
// with the field path, else the backend guidance, message or code.
export function issueText(issue: unknown, locale: string, missing: string): string {
  if (typeof issue === 'string') return issue;
  if (!issue || typeof issue !== 'object' || Array.isArray(issue)) return missing;
  const item = issue as Record<string, unknown>;
  const code = text(item.code);
  if (code) {
    const key = `casespec.issue.${code}`;
    const reason = translate(locale, key);
    if (reason !== key) {
      const field = text(item.field);
      return field && field !== 'spec' ? `${reason} (${field})` : reason;
    }
  }
  // A PVT range message names the node, value and margin; its guidance is generic.
  if (code?.startsWith('pvt_range_')) return text(item.message) ?? text(item.guidance) ?? code;
  return text(item.guidance) ?? text(item.message) ?? code ?? missing;
}
