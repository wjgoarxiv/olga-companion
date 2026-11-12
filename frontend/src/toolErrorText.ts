import { translate } from './i18n/index.ts';

// Backend tool errors stay English for the model; the card shows the common ones localized.
const PATTERNS: ReadonlyArray<readonly [RegExp, string]> = [
  [/^input file not found: (.+)$/s, 'toolError.inputNotFound'],
  [/^result file not found: (.+)$/s, 'toolError.resultNotFound'],
  [/^Could not read a series for (.+) from (.+)\.$/s, 'toolError.seriesUnreadable'],
];

export function toolErrorText(error: string, locale: string): string {
  for (const [pattern, key] of PATTERNS) {
    const match = pattern.exec(error);
    if (match) return translate(locale, key, { name: match[1], file: match[2] ?? '' });
  }
  if (/[가-힣]/.test(error)) return error;
  return translate(locale, 'toolError.raw', { text: error });
}
