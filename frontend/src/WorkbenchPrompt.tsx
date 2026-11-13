import type { ReactNode } from 'react';

type WorkbenchPromptProps = {
  readonly kicker: string;
  readonly title: string;
  readonly description: string;
  readonly contextLabel: string;
  readonly contextValue: string;
  readonly contextDetail: string;
  readonly className?: string;
  readonly children?: ReactNode;
};

export function WorkbenchPrompt({
  kicker,
  title,
  description,
  contextLabel,
  contextValue,
  contextDetail,
  className,
  children,
}: WorkbenchPromptProps) {
  return (
    <section className={`workbench-prompt${className ? ` ${className}` : ''}`} aria-label={title}>
      <div className="workbench-prompt-hero">
        <div className="workbench-prompt-intro">
          <p className="workbench-prompt-kicker">{kicker}</p>
          <h2>{title}</h2>
          <p className="workbench-prompt-description">{description}</p>
        </div>
        <aside className="workbench-prompt-context" aria-label={contextLabel}>
          <span>{contextLabel}</span>
          <strong>{contextValue}</strong>
          <em>{contextDetail}</em>
        </aside>
      </div>
      {children && <div className="workbench-prompt-body">{children}</div>}
    </section>
  );
}
