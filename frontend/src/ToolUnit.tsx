import { useState } from 'react';
import { lifecycleLabelKey, useLocale } from './i18n/index.ts';
import EvidenceBlock from './EvidenceBlock';
import { toolErrorText } from './toolErrorText.ts';
import type { ToolLifecycleState } from './approvalActionLifecycle';

export type ToolStatus = ToolLifecycleState;

/** A tool call and the evidence it produced, as one grouped, collapsible unit —
 *  instead of an orphaned chip and a separate evidence block that read as
 *  unrelated siblings. The status dot pulses while running; a refusal that is
 *  waiting on human approval reads as a quiet "awaiting" state, never a red
 *  error (the approval card right below already carries that message). */
export default function ToolUnit({
  name,
  status,
  result,
  currentWorkspaceGeneration,
}: {
  name: string;
  status: ToolStatus;
  result?: Record<string, unknown>;
  currentWorkspaceGeneration?: number;
}) {
  const { t, locale } = useLocale();
  const statusLabel = result?.code === 'approval_unavailable'
    ? t('approval.expiredTitle')
    : t(lifecycleLabelKey(status));
  const hasResultBody = result !== undefined && Object.keys(result).length > 0;
  const isErrorOnly = result !== undefined && Object.keys(result).every((key) => key === 'error' || key === 'ok' || key === 'code');
  const hasBody = hasResultBody && !(status === 'failed' && isErrorOnly);
  const [open, setOpen] = useState(true);
  const errorText = status === 'failed' ? toolErrorText(String(result?.error ?? 'failed'), locale) : '';

  return (
    <div className={`tool-unit ${status}`} data-testid="tool-unit">
      <button
        type="button"
        className="tool-head"
        onClick={() => hasBody && setOpen((v) => !v)}
        aria-expanded={hasBody ? open : undefined}
        aria-label={hasBody
          ? t(open ? 'tool.ariaOpen' : 'tool.ariaClosed', { name, state: statusLabel })
          : t('tool.ariaPlain', { name, state: statusLabel })}
        disabled={!hasBody}
      >
        <span className="tool-dot" aria-hidden />
        <span className="tool-name">{name}</span>
        <span className="tool-state">{statusLabel}</span>
        {hasBody && <span className="tool-chev" aria-hidden>{open ? '−' : '+'}</span>}
      </button>
      {hasBody && open && <EvidenceBlock name={name} result={result} currentWorkspaceGeneration={currentWorkspaceGeneration} />}
      {status === 'failed' && <p className="tool-error">{errorText}</p>}
    </div>
  );
}
