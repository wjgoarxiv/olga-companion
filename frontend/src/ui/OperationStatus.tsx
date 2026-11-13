import type { ReactNode } from 'react';

export type OperationStatusTone = 'busy' | 'info' | 'success' | 'error';

type OperationStatusProps = {
  readonly tone: OperationStatusTone;
  readonly title: string;
  readonly detail?: ReactNode;
  readonly action?: ReactNode;
  readonly className?: string;
};

export function OperationStatus({ tone, title, detail, action, className }: OperationStatusProps) {
  return (
    <div
      className={['operation-status', `operation-status-${tone}`, className].filter(Boolean).join(' ')}
      role={tone === 'error' ? 'alert' : 'status'}
      aria-live={tone === 'error' ? 'assertive' : 'polite'}
    >
      <div className="operation-status-copy">
        <strong>{title}</strong>
        {detail && <span>{detail}</span>}
      </div>
      {action && <div className="operation-status-action">{action}</div>}
    </div>
  );
}
