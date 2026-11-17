import type { ReactNode } from 'react';

type ReceiptProps = {
  readonly title: string;
  readonly meta?: ReactNode;
  readonly actions?: ReactNode;
  readonly children?: ReactNode;
  readonly className?: string;
};

export function Receipt({ title, meta, actions, children, className }: ReceiptProps) {
  return (
    <section className={['receipt', className].filter(Boolean).join(' ')} aria-label={title} tabIndex={-1}>
      <div className="receipt-copy">
        <strong className="receipt-title">{title}</strong>
        {meta && <span className="receipt-meta">{meta}</span>}
      </div>
      {children && <div className="receipt-body">{children}</div>}
      {actions && <div className="receipt-actions">{actions}</div>}
    </section>
  );
}
