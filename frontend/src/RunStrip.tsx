import { useEffect, useRef, useState } from 'react';
import { subscribeTaskbarObservations } from './taskbarRunFeed.mjs';
import { runStripModel, durationParts, STRIP_LINGER_MS } from './runStripModel.mjs';
import { runCancel } from './runApi';
import { useLocale } from './i18n/index.ts';
import { RollingNumber } from './ui/RollingNumber';

type Observation = { readonly kind: string; readonly status?: { readonly run_id?: string; readonly state?: string } };
const TERMINAL = new Set(['completed', 'failed', 'cancelled', 'timed_out']);

type RunStripProps = {
  readonly onOpenRun: () => void;
  readonly onOpenResults: () => void;
};

/** One line under the top bar while a run goes, so its progress is visible from every screen. */
export function RunStrip({ onOpenRun, onOpenResults }: RunStripProps) {
  const { t } = useLocale();
  const [observation, setObservation] = useState<Observation | null>(null);
  const [terminalSince, setTerminalSince] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [dismissed, setDismissed] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);

  const lastRef = useRef<{ runId: string | undefined; since: number | null }>({ runId: undefined, since: null });

  useEffect(() => subscribeTaskbarObservations((next: Observation) => {
    if (next.kind !== 'run') return;
    const runId = next.status?.run_id;
    const last = lastRef.current;
    const sameRun = last.runId === runId;
    const ended = TERMINAL.has(String(next.status?.state));
    const since = ended ? (sameRun && last.since != null ? last.since : Date.now()) : null;
    lastRef.current = { runId, since };
    if (!sameRun) { setDismissed(null); setStopping(false); }
    setTerminalSince(since);
    setObservation(next);
    setNow(Date.now());
  }), []);

  // Only to let a finished run's line go away on time; live runs tick with each observation.
  useEffect(() => {
    if (terminalSince == null) return undefined;
    const timer = setTimeout(() => setNow(Date.now()), STRIP_LINGER_MS + 50);
    return () => clearTimeout(timer);
  }, [terminalSince]);

  const view = runStripModel(observation, { now, terminalSince });
  if (!view.visible || dismissed === view.runId) return null;

  const stop = async () => {
    setStopping(true);
    try { await runCancel(view.runId); } catch { setStopping(false); }
  };
  const duration = (seconds: number) => {
    const d = durationParts(seconds);
    if (d.h > 0) return t('runStrip.durHM', { h: d.h, m: String(d.m).padStart(2, '0') });
    if (d.total >= 60) return t('runStrip.durM', { m: d.m });
    return t('runStrip.durS', { s: d.s });
  };
  const label = t(`runStrip.${view.tone}` as 'runStrip.running');
  const facts = [
    view.simTimeS != null ? t('runStrip.simTime', { value: duration(view.simTimeS) }) : '',
    view.elapsedS != null && view.tone !== 'completed' && view.tone !== 'failed' ? t('runStrip.elapsed', { value: duration(view.elapsedS) }) : '',
    view.etaS != null ? t('runStrip.eta', { value: duration(view.etaS) }) : '',
  ].filter(Boolean);

  return (
    <section className="run-strip" data-tone={view.tone} aria-label={t('runStrip.aria')}>
      <span className="run-strip-dot" aria-hidden="true" />
      <p className="run-strip-text" aria-live="polite">
        <b>{label}</b>
        {view.caseName && <span className="run-strip-case">{view.caseName}</span>}
        {view.percent != null && <span className="run-strip-pct"><RollingNumber value={view.percent} format={(n) => `${n}%`} /></span>}
      </p>
      <span className="run-strip-track" data-waiting={view.percent == null ? 'true' : undefined}>
        <progress max={100} value={view.percent ?? undefined} aria-label={t('runStrip.aria')} />
      </span>
      {facts.length > 0 && <p className="run-strip-facts">{facts.join(' · ')}</p>}
      <div className="run-strip-actions">
        {view.canOpenResults
          ? <button type="button" className="run-strip-btn is-primary" onClick={onOpenResults}>{t('runStrip.results')}</button>
          : <button type="button" className="run-strip-btn" onClick={onOpenRun}>{t('runStrip.open')}</button>}
        {view.canStop && <button type="button" className="run-strip-btn" onClick={stop} disabled={stopping}>{stopping ? t('runStrip.stopping') : t('runStrip.stop')}</button>}
        {(view.tone === 'completed' || view.tone === 'failed') && (
          <button type="button" className="run-strip-btn is-quiet" onClick={() => setDismissed(view.runId)} aria-label={t('runStrip.dismiss')}>{t('runStrip.close')}</button>
        )}
      </div>
    </section>
  );
}
