import type { CSSProperties } from 'react';
import { useRunConsoleEntries, useRunConsoleSnapshot } from './runConsole';
import { useLocale } from './i18n/index.ts';
import { runStateLabel } from './runReason.ts';

export function RunConsolePanel() {
  const { t } = useLocale();
  const entries = useRunConsoleEntries();
  const snapshot = useRunConsoleSnapshot();
  const stateLabel = snapshot.state == null
    ? null
    : snapshot.state === 'preview'
      ? t('run.consolePreviewState')
      : runStateLabel(snapshot.state, t);
  return (
    <div className="run-console" aria-label={t('run.logLabel')}>
      <p className="run-console-sim tabular-nums">
        <span><strong>{t('run.consoleState')}</strong> {stateLabel ?? '—'}</span>
        {snapshot.simTimeS != null && (
          <span><strong>{t('run.simTime')}</strong> {snapshot.simTimeS.toLocaleString()} s</span>
        )}
        {snapshot.exitCode != null && (
          <span><strong>{t('run.exit')}</strong> {snapshot.exitCode}</span>
        )}
      </p>
      {entries.length > 0 ? (
        <ol className="run-console-entries">
          {entries.map((entry, index) => (
            <li
              key={entry.id}
              className={`run-console-entry run-console-${entry.tone}`}
              style={{ '--i': Math.min(index, 11) } as CSSProperties}
            >
              {entry.text}
            </li>
          ))}
        </ol>
      ) : (
        <p className="run-console-empty">{t('run.consoleEmpty')}</p>
      )}
      {snapshot.logTail.length > 0 && (
        <pre className="run-console-tail" tabIndex={0} aria-label={t('run.logLabel')}>{snapshot.logTail.join('\n')}</pre>
      )}
    </div>
  );
}
