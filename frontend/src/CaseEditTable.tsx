import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { Button } from './ui/Button';
import { ActivityLoader } from './ui/ActivityLoader';
import { OperationStatus } from './ui/OperationStatus';
import { useLocale } from './i18n/index.ts';
import {
  buildOperations, cellField, changedRows, conflictKey, displayUnit, unitInBrackets, withUnit, displayValue, formatDisplay, planReasons,
  type CaseEditRow,
} from './caseEditModel.mjs';
import {
  CaseEditError, fetchCaseEditRows, planCaseEdit, publishCaseEdit,
  type CaseEditPlan, type CaseEditRows,
} from './caseEditApi';
import { setActiveCase } from './workspaceApi';
import { KeywordCoverageMap } from './CaseChecks';
import KeywordCaption from './KeywordCaption';
import { CASE_EDIT_ACTIVE_CHANGED_EVENT, CASE_EDIT_SAVED_EVENT } from './shell/workspaceEvents';
import './styles/case-edit.css';

type Phase = 'loading' | 'editing' | 'planning' | 'review' | 'publishing' | 'published';
type Problem = { readonly kind: 'conflict' | 'refused'; readonly title: string; readonly reasons: readonly string[] };

type CaseEditTableProps = {
  /** Workspace-relative path of the case being edited. */
  readonly rel: string;
  /** Called with the workspace-relative path of the saved copy. */
  readonly onSaved: (rel: string) => void;
  readonly onClose: () => void;
  /** The row a stopped run named; it is marked and focused, never filled in. */
  readonly highlightRowId?: string | null;
};

/** At most this many changed values go into one review, as the server accepts. */
const MAX_CHANGES = 20;

/** One reviewed change, in the units the table shows; kept by the table, not parsed from server text. */
export type ReviewedChange = { readonly row: CaseEditRow; readonly before: string; readonly after: string };

/** One line of the review card; a schedule or series row says what the new value replaces. */
export function ReviewedChangeItem({ change }: { readonly change: ReviewedChange }) {
  const { t } = useLocale();
  return (
    <li>
      <span className="case-edit-target">{`${change.row.target} ${t(`caseEdit.field.${change.row.field}`)}`}</span>
      <span className="case-edit-from">{change.before}</span>
      <span aria-hidden="true">→</span>
      <span className="sr-only">{t('caseEdit.to')}</span>
      <span className="case-edit-to">{change.after}</span>
      {change.row.note && <span className="case-edit-review-note" role="note">{t(`caseEdit.reviewNote.${change.row.note}`, { value: change.after })}</span>}
    </li>
  );
}

/** The user's own edit of one case: change values, review the compiled copy, approve to save it as a new file. */
export function CaseEditTable({ rel, onSaved, onClose, highlightRowId = null }: CaseEditTableProps) {
  const { t } = useLocale();
  const [phase, setPhase] = useState<Phase>('loading');
  const [rows, setRows] = useState<CaseEditRows | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [cellError, setCellError] = useState<{ rowId: string | null; key: string } | null>(null);
  const [plan, setPlan] = useState<CaseEditPlan | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [published, setPublished] = useState<string | null>(null);
  const [restored, setRestored] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [restoreProblem, setRestoreProblem] = useState<string | null>(null);
  const [reviewed, setReviewed] = useState<readonly ReviewedChange[]>([]);
  const [focusTick, setFocusTick] = useState(0);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const tableRef = useRef<HTMLTableElement>(null);

  async function load() {
    setPhase('loading');
    setProblem(null);
    setPlan(null);
    setCellError(null);
    try {
      const next = await fetchCaseEditRows(rel);
      setRows(next);
      setDrafts(Object.fromEntries(next.rows.map((row) => [row.id, formatDisplay(row)])));
      setPhase('editing');
    } catch (cause) {
      setProblem({ kind: 'refused', title: t('caseEdit.loadFailed'), reasons: [cause instanceof Error ? cause.message : String(cause)] });
      setPhase('editing');
    }
  }

  useEffect(() => { void load(); }, [rel]);
  // A stopped run's pointer: move to the row it names; the value stays as the case has it.
  const pointedRef = useRef<string | null>(null);
  useEffect(() => {
    // Point once per row id: a reload after approval must not pull focus back.
    if (!highlightRowId || !rows || pointedRef.current === highlightRowId) return;
    pointedRef.current = highlightRowId;
    const cell = tableRef.current?.querySelector<HTMLInputElement>(`tr[data-row-id="${CSS.escape(highlightRowId)}"] input`);
    cell?.scrollIntoView({ block: 'center' });
    cell?.focus();
  }, [highlightRowId, rows]);
  useEffect(() => { headingRef.current?.focus(); }, [phase === 'review', phase === 'published', focusTick]);
  useEffect(() => {
    if (cellError?.rowId) tableRef.current?.querySelector<HTMLInputElement>('[aria-invalid="true"]')?.focus();
  }, [cellError]);

  function fail(cause: unknown, back: Phase) {
    if (cause instanceof CaseEditError) {
      const conflict = conflictKey(cause.code);
      if (conflict) {
        setPlan(null);
        setProblem({ kind: 'conflict', title: t(conflict), reasons: [] });
        setPhase('editing');
        setFocusTick((tick) => tick + 1);
        return;
      }
      setProblem({
        kind: 'refused',
        title: t(cause.code === 'uncertain' ? 'caseEdit.uncertain' : 'caseEdit.refused'),
        reasons: cause.message ? [cause.message] : [],
      });
    } else {
      setProblem({ kind: 'refused', title: t('caseEdit.refused'), reasons: [cause instanceof Error ? cause.message : String(cause)] });
    }
    setPhase(back);
    setFocusTick((tick) => tick + 1);
  }

  async function review() {
    if (!rows) return;
    const built = buildOperations(rows.rows, drafts);
    if (!built.ok) {
      setCellError({ rowId: built.rowId, key: built.error });
      return;
    }
    const picked = changedRows(rows.rows, drafts);
    if (picked.length > MAX_CHANGES) {
      setCellError({ rowId: null, key: 'caseEdit.error.tooMany' });
      return;
    }
    setCellError(null);
    setProblem(null);
    setPhase('planning');
    try {
      const next = await planCaseEdit(rows, built.operations);
      if (!next.publishable) {
        setProblem({ kind: 'refused', title: t('caseEdit.refused'), reasons: planReasons(next) });
        setPhase('editing');
        return;
      }
      setReviewed(picked.map((row) => ({
        row,
        before: withUnit(row, formatDisplay(row)),
        after: withUnit(row, (drafts[row.id] ?? '').trim()),
      })));
      setPlan(next);
      setPhase('review');
    } catch (cause) {
      fail(cause, 'editing');
    }
  }

  async function approve() {
    if (!plan) return;
    setProblem(null);
    setPhase('publishing');
    try {
      const receipt = await publishCaseEdit(plan);
      setPublished(receipt.destination_rel);
      setPhase('published');
      onSaved(receipt.destination_rel);
      window.dispatchEvent(new CustomEvent(CASE_EDIT_SAVED_EVENT, { detail: { rel: receipt.destination_rel } }));
      window.dispatchEvent(new CustomEvent(CASE_EDIT_ACTIVE_CHANGED_EVENT));
    } catch (cause) {
      fail(cause, 'review');
    }
  }

  async function backToOriginal() {
    if (!rows || restoring) return;
    setRestoring(true);
    setRestoreProblem(null);
    try {
      await setActiveCase(rows.source, rows.context_generation);
      setRestored(true);
      window.dispatchEvent(new CustomEvent(CASE_EDIT_ACTIVE_CHANGED_EVENT));
    } catch (cause) {
      setRestoreProblem(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setRestoring(false);
    }
  }

  function onCellKey(event: KeyboardEvent<HTMLInputElement>, row: CaseEditRow) {
    if (event.key === 'Escape') {
      event.preventDefault();
      setDrafts((current) => ({ ...current, [row.id]: formatDisplay(row) }));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      void review();
    }
  }

  const editable = phase === 'editing' || phase === 'planning';
  const changed = rows ? new Set(changedRows(rows.rows, drafts).map((row) => row.id)) : new Set<string>();
  const fileName = rel.split('/').pop() ?? rel;

  return (
    <section className="case-edit" aria-labelledby="case-edit-title">
      <header className="case-edit-head">
        <div>
          <h3 id="case-edit-title" ref={headingRef} tabIndex={-1}>{t('caseEdit.title')}</h3>
          <p className="case-edit-lede">
            {rows && !rows.marked ? t('caseEdit.ledeEndOnly', { name: fileName }) : t('caseEdit.lede', { name: fileName })}
          </p>
        </div>
        <Button variant="quiet" onClick={onClose}>{t('caseEdit.close')}</Button>
      </header>

      {phase === 'loading' && <ActivityLoader className="case-edit-loading" loadingLabel={t('caseEdit.loading')} />}

      {problem && (
        <OperationStatus
          className="case-edit-status"
          tone="error"
          title={problem.title}
          detail={problem.reasons.length > 0 ? problem.reasons.join(' · ') : undefined}
          action={problem.kind === 'conflict'
            ? <Button variant="secondary" onClick={() => { void load(); }}>{t('caseEdit.reload')}</Button>
            : undefined}
        />
      )}

      {rows && rows.rows.length === 0 && phase !== 'loading' && (
        <OperationStatus
          className="case-edit-status"
          tone="info"
          title={rows.reason === 'not_exact_compile' ? t('caseEdit.notExact') : t('caseEdit.noRows')}
        />
      )}

      {rows && rows.rows.length > 0 && (phase === 'editing' || phase === 'planning') && (
        <>
          <div className="case-edit-scroll">
            <table className="case-edit-table" ref={tableRef}>
              <caption>{t('caseEdit.caption')}</caption>
              <thead>
                <tr>
                  <th scope="col">{t('caseEdit.col.target')}</th>
                  <th scope="col">{t('caseEdit.col.value')}</th>
                  <th scope="col">{t('caseEdit.col.unit')}</th>
                  <th scope="col">{t('caseEdit.col.current')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.rows.map((row) => {
                  const isChanged = changed.has(row.id);
                  const errorHere = cellError?.rowId === row.id;
                  const noteId = row.note ? `case-edit-note-${row.id}` : undefined;
                  const errorId = errorHere ? `case-edit-error-${row.id}` : undefined;
                  return (
                    <tr key={row.id} data-row-id={row.id} aria-current={row.id === highlightRowId ? 'true' : undefined}
                      className={[isChanged ? 'is-changed' : '', row.id === highlightRowId ? 'is-pointed' : ''].filter(Boolean).join(' ') || undefined}>
                      <th scope="row">
                        <span className="case-edit-target">{row.target}</span>
                        <span className="case-edit-field">{t(`caseEdit.field.${row.field}`)}</span>
                        <KeywordCaption keyword={row.keyword} />
                        {row.note && <span id={noteId} className="case-edit-note">{t(`caseEdit.note.${row.note}`)}</span>}
                      </th>
                      <td>
                        <input
                          className="case-edit-input"
                          type="text"
                          inputMode="decimal"
                          autoComplete="off"
                          spellCheck={false}
                          value={drafts[row.id] ?? ''}
                          disabled={!editable || phase === 'planning'}
                          aria-label={`${row.target} ${t(`caseEdit.field.${row.field}`)}${unitInBrackets(row)}`}
                          aria-invalid={errorHere || undefined}
                          aria-describedby={[noteId, errorId].filter(Boolean).join(' ') || undefined}
                          onChange={(event) => {
                            const value = event.target.value;
                            setDrafts((current) => ({ ...current, [row.id]: value }));
                            if (errorHere) setCellError(null);
                          }}
                          onKeyDown={(event) => onCellKey(event, row)}
                        />
                        {errorHere && cellError && <span id={errorId} className="case-edit-cell-error" role="alert">{t(cellError.key)}</span>}
                      </td>
                      <td className="case-edit-unit">{displayUnit(cellField(row))}</td>
                      <td className="case-edit-current">{displayValue(row)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {cellError && cellError.rowId === null && (
            <p className="case-edit-hint" role="alert">{t(cellError.key)}</p>
          )}
          <p className="case-edit-hint">{t('caseEdit.keys')}</p>
          {rows?.coverage && <KeywordCoverageMap coverage={rows.coverage} />}
          <div className="case-edit-actions">
            <Button
              variant="primary"
              onClick={() => { void review(); }}
              disabled={changed.size === 0}
              busy={phase === 'planning'}
              busyLabel={t('caseEdit.reviewing')}
            >
              {t('caseEdit.review', { count: changed.size })}
            </Button>
            <Button
              variant="secondary"
              onClick={() => { setDrafts(Object.fromEntries(rows.rows.map((row) => [row.id, formatDisplay(row)]))); setCellError(null); }}
              disabled={changed.size === 0 || phase === 'planning'}
            >
              {t('caseEdit.reset')}
            </Button>
          </div>
        </>
      )}

      {plan && (phase === 'review' || phase === 'publishing') && (
        <div className="case-edit-review" role="region" aria-label={t('caseEdit.reviewTitle')}>
          <h4>{t('caseEdit.reviewTitle')}</h4>
          <ul className="case-edit-changes">
            {reviewed.map((change) => <ReviewedChangeItem key={change.row.id} change={change} />)}
          </ul>
          <OperationStatus
            className="case-edit-status"
            tone="success"
            title={t('caseEdit.validated')}
            detail={t('caseEdit.newFile', { name: plan.destination_rel.split('/').pop() ?? plan.destination_rel })}
          />
          {(plan.text_diff ?? []).length > 0 && (
            <details className="case-edit-diff">
              <summary>{t('caseEdit.textDiff')}</summary>
              <pre>{(plan.text_diff ?? []).join('\n')}{plan.diff_truncated ? `\n${t('caseEdit.diffTruncated')}` : ''}</pre>
            </details>
          )}
          <div className="case-edit-actions">
            <Button variant="primary" onClick={() => { void approve(); }} busy={phase === 'publishing'} busyLabel={t('caseEdit.saving')}>
              {t('caseEdit.approve')}
            </Button>
            <Button variant="secondary" onClick={() => { setPlan(null); setPhase('editing'); }} disabled={phase === 'publishing'}>
              {t('caseEdit.backToEdit')}
            </Button>
          </div>
        </div>
      )}

      {phase === 'published' && published && (
        <div className="case-edit-review">
          <OperationStatus
            className="case-edit-status"
            tone="success"
            title={restored ? t('caseEdit.restored', { name: fileName }) : t('caseEdit.saved', { name: published.split('/').pop() ?? published })}
            detail={restored ? undefined : t('caseEdit.savedDetail', { name: fileName })}
          />
          {restoreProblem && (
            <OperationStatus className="case-edit-status" tone="error" title={t('caseEdit.restoreFailed')} detail={restoreProblem} />
          )}
          <div className="case-edit-actions">
            {!restored && (
              <Button variant="secondary" onClick={() => { void backToOriginal(); }} busy={restoring} busyLabel={t('caseEdit.restoring')}>
                {t('caseEdit.backToOriginal')}
              </Button>
            )}
            <Button variant="quiet" onClick={onClose}>{t('caseEdit.close')}</Button>
          </div>
        </div>
      )}
    </section>
  );
}
