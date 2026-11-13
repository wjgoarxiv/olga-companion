import type { ReactElement, ReactNode } from 'react';

export type LogState = 'done' | 'current' | 'failed' | 'todo';

const TAG: Record<LogState, string> = { done: 'OK', current: '..', failed: 'FAIL', todo: '\u00a0' };

/** Terminal-window frame shared by the boot and shutdown overlays. */
export function LifecycleWindow({
  process,
  children,
}: {
  process: string;
  children: ReactNode;
}): ReactElement {
  return (
    <section className="lc-window">
      <header className="lc-titlebar">
        <svg className="lc-mark" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M0 0H16V16H0ZM1 1V15H15V1Z" fillRule="evenodd" />
          <path className="lc-mark-prompt" d="M3.5 4.5 7 8l-3.5 3.5M8.5 11.5h3" />
        </svg>
        <span className="lc-name">OLGA COMPANION</span>
        <span className="lc-process">{process}</span>
      </header>
      <div className="lc-body">{children}</div>
    </section>
  );
}

/** A pipe with liquid slugs stepping through it; the outlet shows the result. */
export function FlowScene({ result = 'flowing' }: { result?: 'flowing' | 'ok' | 'fail' }): ReactElement {
  return (
    <div className={`lc-scene is-${result}`} aria-hidden="true">
      <span className="lc-scene-node" />
      <span className="lc-scene-pipe">
        <span className="lc-scene-slugs">
          <i />
          <i />
          <i />
        </span>
      </span>
      <span className="lc-scene-node is-outlet" />
    </div>
  );
}

export function LogLine({ state, children }: { state: LogState; children: ReactNode }): ReactElement {
  return (
    <li className={`lc-line is-${state}`} aria-current={state === 'current' ? 'step' : undefined}>
      <span className="lc-tag" aria-hidden="true">{TAG[state]}</span>
      <span>{children}</span>
    </li>
  );
}
