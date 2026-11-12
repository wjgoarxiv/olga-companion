import { ko } from './i18n/ko.ts';
import type { I18nKey } from './i18n/ko.ts';

export type ReasonText = (key: I18nKey, vars?: Record<string, string | number>) => string;

export function reasonParams(raw: unknown): Record<string, string | number> {
  const params: Record<string, string | number> = {};
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return params;
  for (const [name, value] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof value === 'string') params[name] = value;
    else if (typeof value === 'number' && Number.isFinite(value)) params[name] = value;
    else if (Array.isArray(value)) params[name] = value.map((item) => String(item)).join(', ');
  }
  return params;
}

export interface ReasonDetect {
  readonly rationale: string;
  readonly reason_code?: string | null;
  readonly reason_params?: Readonly<Record<string, string | number | readonly (string | number)[]>> | null;
  readonly selection_status?: string | null;
  readonly version?: string | null;
  readonly kind?: string | null;
}

const NO_RECORD_PATTERN = /^no_run_record/;

function reasonKey(code: string): string {
  return `run.reason.${code}`;
}

function engineKindLabel(kind: string | null | undefined, t: ReasonText): string {
  if (kind === 'opi') return t('run.launcher.opi');
  if (kind === 'engine') return t('run.launcher.engine');
  if (kind === 'script') return t('run.launcher.script');
  return kind || t('run.launcher.unknown');
}

export function reasonKeyExists(code: string): boolean {
  return Object.prototype.hasOwnProperty.call(ko, reasonKey(code));
}

/** Environment line for the selected engine. A recovered record below proves a
 *  run happened, so a "no record" claim must yield to the engine selection. */
export function formatRunReason(
  detect: ReasonDetect,
  t: ReasonText,
  options?: { readonly hasRecoveredRecord?: boolean },
): string {
  const code = detect.reason_code ?? null;
  if (options?.hasRecoveredRecord === true && (code == null || NO_RECORD_PATTERN.test(code))) {
    return t('run.reason.selectedEngine', {
      engine: `OLGA ${detect.version || t('run.versionUnknown')} · ${engineKindLabel(detect.kind, t)}`,
    });
  }
  if (code) {
    const params: Record<string, string | number> = {};
    for (const [name, value] of Object.entries(detect.reason_params ?? {})) {
      params[name] = typeof value === 'string' || typeof value === 'number' ? value : value.join(', ');
    }
    // A code surviving under selection_status selected_candidate is stale
    // (require_candidate overwrote the status): keep it as a reference only.
    if (detect.selection_status === 'selected_candidate') {
      return t('run.reason.generic', { code, ...params });
    }
    if (reasonKeyExists(code)) {
      return t(reasonKey(code) as I18nKey, params);
    }
    return t('run.reason.generic', { code, ...params });
  }
  return detect.rationale || t('run.reason.missing');
}

const KNOWN_RUN_STATES = new Set([
  'ready',
  'starting',
  'planned',
  'running',
  'finalizing',
  'completed',
  'failed',
  'cancelled',
  'timed_out',
  'supervision_unknown',
  'recovery_unknown',
  'last_known',
]);

export interface ReasonParts {
  readonly text: string;
  readonly code: string | null;
}

/** Sentence/code split of formatRunReason for the detection block: the
 *  visible sentence never carries the raw code; a stale or unknown code is
 *  returned separately so the caller can disclose it in <details>. */
export function formatRunReasonParts(
  detect: ReasonDetect,
  t: ReasonText,
  options?: { readonly hasRecoveredRecord?: boolean },
): ReasonParts {
  const code = detect.reason_code ?? null;
  if (options?.hasRecoveredRecord === true && (code == null || NO_RECORD_PATTERN.test(code))) {
    return {
      text: t('run.reason.selectedEngine', {
        engine: `OLGA ${detect.version || t('run.versionUnknown')} · ${engineKindLabel(detect.kind, t)}`,
      }),
      code: null,
    };
  }
  if (code) {
    // A code surviving under selection_status selected_candidate is stale
    // (require_candidate overwrote the status): human sentence only, the
    // code stays available as a reference.
    if (detect.selection_status === 'selected_candidate' || !reasonKeyExists(code)) {
      return { text: t('run.reason.selectedEnvironment'), code };
    }
    return { text: t(reasonKey(code) as I18nKey, paramsOf(detect)), code: null };
  }
  return { text: detect.rationale || t('run.reason.missing'), code: null };
}

function paramsOf(detect: ReasonDetect): Record<string, string | number> {
  const params: Record<string, string | number> = {};
  for (const [name, value] of Object.entries(detect.reason_params ?? {})) {
    params[name] = typeof value === 'string' || typeof value === 'number' ? value : value.join(', ');
  }
  return params;
}

export function runStateLabel(state: string, t: ReasonText): string {
  if (!KNOWN_RUN_STATES.has(state)) return state;
  return t(`run.state.${state}` as I18nKey);
}
