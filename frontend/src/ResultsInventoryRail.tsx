import type { ResultFile } from './session';
import { useRef, useState } from 'react';
import { useExplorerFilter } from './explorerFilter';
import { useLocale } from './i18n/index.ts';
import { PanelResizeHandle } from './PanelResizeHandle';
import {
  filterResultFiles,
  modifiedLabel,
  receiptBacked,
  resultContextLabel,
  resultStatusKey,
} from './resultPresentation';
import { splitByRoot } from './resultScoping';
import { Button } from './ui/Button';

function filenameParts(name: string): { readonly stem: string; readonly extension: string } {
  const suffixIndex = name.lastIndexOf('.');
  return suffixIndex > 0
    ? { stem: name.slice(0, suffixIndex), extension: name.slice(suffixIndex) }
    : { stem: name, extension: '' };
}

type ResultsInventoryRailProps = {
  readonly results: readonly ResultFile[];
  readonly selected: ResultFile | null;
  readonly rootLabel: string;
  readonly currentRoot?: string | null;
  readonly activeCaseName: string | null;
  readonly inventoryLoading: boolean;
  readonly error: string;
  readonly refreshResults: () => void;
  readonly openFile: (result: ResultFile) => void;
};

export default function ResultsInventoryRail({
  results,
  selected,
  rootLabel,
  currentRoot = null,
  activeCaseName,
  inventoryLoading,
  error,
  refreshResults,
  openFile,
}: ResultsInventoryRailProps) {
  const filesRef = useRef<HTMLElement | null>(null);
  const [filter, setExplorerFilter] = useExplorerFilter();
  const { t, locale } = useLocale();
  // Hidden-other applies FIRST at workspace-root level; without a current
  // root the rail is unwired and keeps the pre-scoping show-everything pool.
  const [showOther, setShowOther] = useState(false);
  const { visible: rootVisible, hiddenOther } = splitByRoot(results, currentRoot, showOther);
  const rootHiding = hiddenOther > 0 && !showOther;
  const caseResults = activeCaseName ? rootVisible.filter((result) => result.source_name === activeCaseName) : [];
  // Open on the active case's own results; a person starting out should not wade through every run.
  const [caseOnlyChoice, setCaseOnlyChoice] = useState<boolean | null>(null);
  const caseOnly = (caseOnlyChoice ?? true) && caseResults.length > 0;
  const pool = caseOnly ? caseResults : rootVisible;
  // A result opened from elsewhere (for example from Run) must stay visible in the list.
  const visiblePool = selected && !pool.some((item) => item.id === selected.id) ? [selected, ...pool] : pool;
  const newestFirst = [...visiblePool].sort((a, b) => b.modified_ns - a.modified_ns);
  const shownResults = filterResultFiles(newestFirst, filter);
  const rootEmptied = rootVisible.length === 0 && rootHiding && filter === '';
  const countTitle = inventoryLoading
    ? results.length > 0
      ? t('results.refreshing')
      : t('results.scanning')
    : filter || caseOnly
      ? t('results.countFiltered', { shown: shownResults.length, total: results.length })
      : t(rootVisible.length === 1 ? 'results.countOne' : 'results.countOther', { count: rootVisible.length });
  return (
    <>
      <aside ref={filesRef} id="results-inventory-sidebar" className={`rv-files${results.length === 0 && !error ? ' empty' : ''}`}>
        <div className="rv-files-head">
          <div className="rv-files-heading">
            <span className="rv-files-kicker">{t('results.kicker')}</span>
            <strong className="rv-files-title" role="status" aria-live="polite" aria-atomic="true">
              {countTitle}
            </strong>
          </div>
          <p className="ws-root rv-files-root" title={rootLabel}>{rootLabel}</p>
          {filter !== '' && (
            <p className="rv-filter-note" role="status">
              <span>{t('results.filteredBy', { filter })}</span>
              <Button variant="quiet" className="rv-clear-filter" onClick={() => setExplorerFilter('')}>{t('results.clearFilter')}</Button>
            </p>
          )}
          {caseResults.length > 0 && (
            <label className="rv-case-only">
              <input type="checkbox" checked={caseOnly} onChange={(event) => setCaseOnlyChoice(event.target.checked)} />
              <span>{t('results.caseOnly', { caseCount: caseResults.length, totalCount: rootVisible.length })}</span>
            </label>
          )}
          {(hiddenOther > 0 || showOther) && (
            <p className="rv-hidden-other">
              <Button
                variant="quiet"
                className="rv-show-other"
                aria-pressed={showOther}
                title={showOther ? t('results.otherShown') : t('results.hiddenOther', { count: hiddenOther })}
                onClick={() => setShowOther((value) => !value)}
              >
                {showOther ? t('results.otherShown') : t('results.hiddenOther', { count: hiddenOther })}
              </Button>
            </p>
          )}
          <div className="rv-files-actions">
            <Button variant="secondary" aria-label={t('results.refreshAria')} onClick={() => { void refreshResults(); }} busy={inventoryLoading} busyLabel={t('results.refreshBusy')}>{t('results.refresh')}</Button>
          </div>
        </div>
        <ul>
          {shownResults.map((f) => {
            const context = receiptBacked(f)
              ? `${f.source_name || `Run ${f.run_id || 'receipt'}`} · ${t(resultStatusKey(f))} · ${modifiedLabel(f.modified_ns, locale)}`
              : resultContextLabel(f);
            const filename = filenameParts(f.name);
            return (
              <li key={f.id}>
                <button
                  type="button"
                  title={`${f.name} — ${context}`}
                  aria-label={`${f.name}, ${context}, ${(f.size / 1024).toFixed(0)} KB`}
                  aria-current={selected?.id === f.id ? 'true' : undefined}
                  className={`ws-file${selected?.id === f.id ? ' active' : ''}`}
                  onClick={() => openFile(f)}
                >
                  <span className="rv-file-label">
                    <span className="ws-file-name case-name">
                      <span className="case-name-stem">{filename.stem}</span>
                      {filename.extension && <span className="case-name-extension">{filename.extension}</span>}
                    </span>
                    <span className="rv-file-context">{context}</span>
                  </span>
                  <span className="ws-file-kb">{(f.size / 1024).toFixed(0)} KB</span>
                </button>
              </li>
            );
          })}
          {results.length > 0 && shownResults.length === 0 && !rootEmptied && (
            <li className="rv-list-empty">
              <span className="empty-list-label">{t('results.noMatch')}</span>
              <span className="empty-list-meta">{t('results.noMatchHint')}</span>
              <Button variant="quiet" className="rv-clear-filter" onClick={() => setExplorerFilter('')}>{t('results.clearFilter')}</Button>
            </li>
          )}
          {rootEmptied && (
            <li className="rv-list-empty">
              <span className="empty-list-label">{t('results.noOutputs')}</span>
              <span className="empty-list-meta">{t('results.inventoryNote')}</span>
            </li>
          )}
          {results.length === 0 && !error && (
            <li className="rv-list-empty">
              <span className="empty-list-label">{inventoryLoading ? t('results.scanning') : t('results.noOutputs')}</span>
              <span className="empty-list-meta">{t('results.inventoryNote')}</span>
            </li>
          )}
        </ul>
      </aside>
      <PanelResizeHandle
        targetRef={filesRef}
        targetId="results-inventory-sidebar"
        label={t('results.resizeRail')}
        storageKey="olga_panel_results_inventory"
        defaultWidth={244}
        minWidth={196}
        maxWidth={440}
      />
    </>
  );
}
