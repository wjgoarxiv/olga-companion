import { translate } from './i18n/index.ts';

// Backend tool errors stay English for the model; the card shows the common ones localized.
const PATTERNS: ReadonlyArray<readonly [RegExp, string]> = [
  [/^input file not found: (.+)$/s, 'toolError.inputNotFound'],
  [/^result file not found: (.+)$/s, 'toolError.resultNotFound'],
  [/^Could not read a series for (.+) from (.+)\.$/s, 'toolError.seriesUnreadable'],
  [/^Rejected by the user\.$/, 'toolError.rejected'],
];

// Stable codes the backend puts beside `error` (see tool_validation.error_payload).
const CODES: ReadonlySet<string> = new Set([
  'path_not_found',
  'path_outside_workspace',
  'unknown_node',
  'table_unreadable',
  'stale_workspace',
  'approval_unavailable',
  'unit_missing',
]);

export function toolErrorCodeKey(code: unknown): string | null {
  return typeof code === 'string' && CODES.has(code) ? `toolError.code.${code}` : null;
}

export function toolErrorText(error: string, locale: string, code?: unknown): string {
  const codeKey = toolErrorCodeKey(code);
  if (codeKey) {
    const quoted = /'([^']+)'/.exec(error);
    return translate(locale, codeKey, { name: quoted ? `'${quoted[1]}'` : '' });
  }
  for (const [pattern, key] of PATTERNS) {
    const match = pattern.exec(error);
    if (match) return translate(locale, key, { name: match[1], file: match[2] ?? '' });
  }
  if (/[가-힣]/.test(error)) return error;
  return translate(locale, 'toolError.raw', { text: error });
}
