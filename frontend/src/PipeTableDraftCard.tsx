import { useEffect, useId, useState } from 'react';
import { useLocale, type TranslateFn } from './i18n/index.ts';
import type { I18nKey } from './i18n/ko.ts';
import { apiFetch } from './sessionTransport';
import TopologyMap from './TopologyMap';
import { expandDraftNetwork, formatDraftReason, type DraftCap, type DraftCountKey, type DraftNetwork, type PipeDraftView } from './pipeTableDraft.ts';

const COUNT_ORDER: readonly DraftCountKey[] = ['flowpaths', 'pipes', 'junctions', 'boundaries', 'valves', 'sections'];

type NetworkState =
  | { readonly phase: 'idle' | 'loading' | 'gone' | 'error' }
  | { readonly phase: 'ready'; readonly network: DraftNetwork };

function useNumber() {
  const { locale } = useLocale();
  return (value: number, digits = 0) => new Intl.NumberFormat(locale === 'en' ? 'en-US' : 'ko-KR', { maximumFractionDigits: digits }).format(value);
}

function Meter({ cap, usage, name }: { readonly cap: DraftCap; readonly usage: string; readonly name: string }) {
  const percent = Math.min(100, Math.round((cap.value / cap.limit) * 100));
  return (
    <li className={`pipe-draft-cap${cap.near ? ' is-near' : ''}`}>
      <span className="pipe-draft-cap-name">{name}</span>
      <span className="pipe-draft-cap-usage">{usage}</span>
      <div className="pipe-draft-meter" role="meter" aria-label={name} aria-valuemin={0} aria-valuemax={cap.limit} aria-valuenow={cap.value} aria-valuetext={usage}>
        <span style={{ width: `${percent}%` }} />
      </div>
    </li>
  );
}

function Issues({ view, t }: { readonly view: PipeDraftView; readonly t: TranslateFn }) {
  return (
    <div className="pipe-draft-section">
      {view.issueCount > view.issues.length && (
        <p className="pipe-draft-meta">{t('pipeDraft.issuesShown', { shown: view.issues.length, count: view.issueCount })}</p>
      )}
      <ol className="pipe-draft-issues" aria-label={t('pipeDraft.issuesAria')}>
        {view.issues.map((issue, index) => (
          <li key={`${issue.row ?? 'table'}:${issue.field}:${index}`}>
            <span className="pipe-draft-issue-where">
              {issue.row === null ? t('pipeDraft.issueTable') : t('pipeDraft.issueRow', { row: issue.row })}
              {issue.field ? ` · ${issue.field}` : ''}
            </span>
            <span className="pipe-draft-issue-reason">{formatDraftReason(issue, t)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Network({ view, t }: { readonly view: PipeDraftView; readonly t: TranslateFn }) {
  const [open, setOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<NetworkState>({ phase: 'idle' });
  const regionId = useId();

  useEffect(() => {
    if (!open || state.phase === 'ready') return undefined;
    const controller = new AbortController();
    setState({ phase: 'loading' });
    void apiFetch(`/api/case-draft/${encodeURIComponent(view.draftId)}/topology`, { signal: controller.signal })
      .then(async (response): Promise<NetworkState> => {
        if (response.status === 404 || response.status === 409) return { phase: 'gone' };
        if (!response.ok) return { phase: 'error' };
        const network = expandDraftNetwork(await response.json());
        return network ? { phase: 'ready', network } : { phase: 'error' };
      })
      .catch((): NetworkState => ({ phase: 'error' }))
      .then((next) => { if (!controller.signal.aborted) setState(next); });
    return () => controller.abort();
  }, [open, attempt]);

  return (
    <div className="pipe-draft-network">
      <button type="button" className="pipe-draft-action" aria-expanded={open} aria-controls={regionId} onClick={() => setOpen((value) => !value)}>
        {open ? t('pipeDraft.hideNetwork') : t('pipeDraft.showNetwork')}
      </button>
      {open && (
        <div id={regionId} className="pipe-draft-map" role="region" aria-label={t('pipeDraft.networkAria')}>
          {state.phase === 'loading' && <p className="pipe-draft-meta" role="status">{t('pipeDraft.networkLoading')}</p>}
          {state.phase === 'gone' && <p className="pipe-draft-problem" role="alert">{t('pipeDraft.networkGone')}</p>}
          {state.phase === 'error' && (
            <div className="pipe-draft-problem" role="alert">
              <p>{t('pipeDraft.networkError')}</p>
              <button type="button" className="pipe-draft-action" onClick={() => setAttempt((value) => value + 1)}>{t('pipeDraft.networkRetry')}</button>
            </div>
          )}
          {state.phase === 'ready' && (
            <>
              <p className="pipe-draft-meta">{t('pipeDraft.networkNote')}</p>
              <TopologyMap nodes={state.network.nodes} edges={state.network.edges} counts={state.network.counts} />
            </>
          )}
        </div>
      )}
    </div>
  );
}

/** One pipe-table draft as evidence: what it holds, whether it fits, how even its sections are,
 *  and the network before anything is saved. A refused import lists its issues and nothing else. */
export default function PipeTableDraftCard({ view }: { readonly view: PipeDraftView }) {
  const { t } = useLocale();
  const number = useNumber();
  const near = view.caps.filter((cap) => cap.near);
  const capNames = near.map((cap) => t(`pipeDraft.cap.${cap.key}` as I18nKey)).join(', ');
  return (
    <div className="evidence-lifecycle pipe-draft" role="group" aria-label={t('pipeDraft.aria')}>
      <header className={`evidence-outcome ${view.ready ? 'is-good' : 'is-attention'}`}>
        <div>
          <strong>{view.ready ? t('pipeDraft.readyTitle') : t('pipeDraft.issuesTitle')}</strong>
          <p className="evidence-prose">
            {!view.ready
              ? t('pipeDraft.issuesDetail')
              : view.sourceName
                ? t('pipeDraft.readyDetail', { revision: view.revision, source: view.sourceName })
                : t('pipeDraft.readyDetailUnnamed', { revision: view.revision })}
          </p>
        </div>
      </header>
      {view.issues.length > 0 && <Issues view={view} t={t} />}
      {view.ready && view.counts && (
        <>
          <dl className="evidence-metrics pipe-draft-counts" aria-label={t('pipeDraft.countsAria')}>
            {COUNT_ORDER.map((key) => (
              <div key={key}><dt>{t(`pipeDraft.count.${key}` as I18nKey)}</dt><dd>{number(view.counts?.[key] ?? 0)}</dd></div>
            ))}
          </dl>
          {view.caps.length > 0 && (
            <div className="pipe-draft-section">
              <h5 className="pipe-draft-heading">{t('pipeDraft.capsTitle')}</h5>
              <p className={`pipe-draft-verdict ${near.length > 0 ? 'is-near' : 'is-ok'}`}>
                {near.length > 0 ? t('pipeDraft.capsNear', { names: capNames }) : t('pipeDraft.capsOk')}
              </p>
              <ul className="pipe-draft-caps">
                {view.caps.map((cap) => (
                  <Meter
                    key={cap.key}
                    cap={cap}
                    name={t(`pipeDraft.cap.${cap.key}` as I18nKey)}
                    usage={t('pipeDraft.capUsage', { value: number(cap.value), limit: number(cap.limit) })}
                  />
                ))}
              </ul>
            </div>
          )}
          {(view.shortest !== null || view.longest !== null || view.worstRatio !== null) && (
            <div className="pipe-draft-section">
              <h5 className="pipe-draft-heading">{t('pipeDraft.statsTitle')}</h5>
              <dl className="evidence-metrics pipe-draft-stats">
                {view.shortest !== null && <div><dt>{t('pipeDraft.stat.shortest')}</dt><dd>{number(view.shortest, 3)} m</dd></div>}
                {view.longest !== null && <div><dt>{t('pipeDraft.stat.longest')}</dt><dd>{number(view.longest, 3)} m</dd></div>}
                {view.worstRatio !== null && <div><dt>{t('pipeDraft.stat.ratio')}</dt><dd>{number(view.worstRatio, 2)}</dd></div>}
              </dl>
              <p className="pipe-draft-meta">{t('pipeDraft.statsHint')}</p>
              {view.junctionWarnings > 0 && <p className="evidence-safety">{t('pipeDraft.junctionWarnings', { count: view.junctionWarnings })}</p>}
            </div>
          )}
          {view.start && (
            <div className="pipe-draft-section">
              <h5 className="pipe-draft-heading">{t('pipeDraft.startTitle')}</h5>
              <dl className="evidence-metrics pipe-draft-stats pipe-draft-start">
                <div><dt>{t('pipeDraft.start.pressure')}</dt><dd>{number(view.start.pressureBar, 2)}</dd></div>
                <div><dt>{t('pipeDraft.start.temperature')}</dt><dd>{number(view.start.temperatureC, 1)}</dd></div>
              </dl>
              <p className="pipe-draft-meta">{t(view.start.stated ? 'pipeDraft.startStated' : 'pipeDraft.startGuessed')}</p>
              {view.startWarning && (
                <p className="evidence-safety">
                  {t('pipeDraft.startWarning', { highest: number(view.startWarning.highestBar, 2), lowest: number(view.startWarning.lowestBar, 2) })}
                </p>
              )}
            </div>
          )}
          {view.applied.length > 0 && (
            <div className="pipe-draft-section">
              <h5 className="pipe-draft-heading">{t('pipeDraft.appliedTitle')}</h5>
              <ul className="evidence-diff-list">{view.applied.map((change) => <li key={change}>{change}</li>)}</ul>
            </div>
          )}
          {view.page && (
            <details className="evidence-audit">
              <summary>{t('pipeDraft.pageSummary', { page: view.page.page, pages: view.page.pages })}</summary>
              <div className="evidence-table-viewport" tabIndex={0} aria-label={t('pipeDraft.pageSummary', { page: view.page.page, pages: view.page.pages })}>
                <table className="evidence-table">
                  <thead>
                    <tr>
                      <th>{t('pipeDraft.col.label')}</th><th>{t('pipeDraft.col.name')}</th><th>{t('pipeDraft.col.route')}</th>
                      <th>{t('pipeDraft.col.pipes')}</th><th>{t('pipeDraft.col.sections')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {view.page.rows.map((row) => (
                      <tr key={row.label}>
                        <th scope="row" className="evidence-value-technical">{row.label}</th>
                        <td className="evidence-value-technical">{row.sourceName}</td>
                        <td className="evidence-value-technical">{row.from} → {row.to}</td>
                        <td>{number(row.pipes)}</td>
                        <td>{number(row.sections)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
          <p className="pipe-draft-meta">{t('pipeDraft.nextStep')}</p>
          <Network view={view} t={t} />
        </>
      )}
    </div>
  );
}
