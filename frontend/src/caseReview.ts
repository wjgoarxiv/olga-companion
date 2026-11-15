import { loadLocale, translate } from './i18n/index.ts';
import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';
import { publishCaseProblems, type CaseProblem } from './shell/caseProblems';
import { recordDirectValidation } from './shell/directValidation';

export const CASE_VALIDATED_EVENT = 'olga:case-validated';

function problemsFromReview(valid: boolean, stdout: string): readonly CaseProblem[] {
  const locale = loadLocale();
  if (valid) {
    return [{
      id: 'case-review-clean',
      severity: 'info',
      title: translate(locale, 'examples.validationClean'),
      source: 'validation',
      nodeId: null,
    }];
  }
  const line = stdout.split('\n').map((item) => item.trim()).find((item) => item.startsWith('[X')) ?? stdout.trim();
  return [{
    id: 'case-review-failed',
    severity: 'error',
    title: translate(locale, 'examples.validationFailed'),
    detail: line.slice(0, 280),
    source: 'validation',
    nodeId: null,
  }];
}

export async function reviewWorkspaceCase(rel: string, caseName: string): Promise<void> {
  try {
    const body = (await jsonOrThrow(await apiFetch('/api/genkey/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: rel }),
    }))) as { valid?: boolean; validation?: { stdout?: string } };
    const valid = body.valid === true;
    publishCaseProblems(problemsFromReview(valid, body.validation?.stdout ?? ''));
    recordDirectValidation(caseName, valid);
    window.dispatchEvent(new CustomEvent(CASE_VALIDATED_EVENT, { detail: { caseName, rel, valid } }));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    publishCaseProblems([{
      id: 'case-review-failed',
      severity: 'error',
      title: translate(loadLocale(), 'examples.validationFailed'),
      detail: message.slice(0, 280),
      source: 'validation',
      nodeId: null,
    }]);
    recordDirectValidation(caseName, false);
    window.dispatchEvent(new CustomEvent(CASE_VALIDATED_EVENT, { detail: { caseName, rel, valid: false } }));
  }
}
