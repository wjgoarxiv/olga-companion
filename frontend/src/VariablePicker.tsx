import { useId, useMemo, useState } from 'react';
import { useLocale } from './i18n/index.ts';
import { filterResultVariables } from './resultPresentation';
import type { ResultVar } from './session';
import { formatUnit } from './formatUnit';
import { resultVariableKey } from './useResultSeriesOverlay';

const PAGE_CAP = 80;

export default function VariablePicker({
  variables,
  plottedKeys,
  disabled,
  onToggle,
}: {
  readonly variables: readonly ResultVar[];
  readonly plottedKeys: readonly string[];
  readonly disabled: boolean;
  readonly onToggle: (variable: ResultVar) => void;
}) {
  const { t, locale } = useLocale();
  const listId = useId();
  const [query, setQuery] = useState('');
  const [showAll, setShowAll] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const shown = useMemo(() => filterResultVariables(variables, query, showAll ? variables.length : PAGE_CAP), [variables, query, showAll]);
  const total = useMemo(() => filterResultVariables(variables, query, variables.length).length, [variables, query]);
  const plotted = useMemo(() => new Set(plottedKeys), [plottedKeys]);
  const activeId = shown.length > 0 ? `${listId}-opt-${Math.min(activeIndex, shown.length - 1)}` : undefined;

  function toggleAt(index: number) {
    const variable = shown[index];
    if (variable) onToggle(variable);
  }

  return (
    <div className="rv-picker">
      <label className="rv-picker-search">
        <span>{t('results.pickVariables')}</span>
        <input
          type="search"
          className="rv-filter"
          placeholder={t('results.filterVarsPlaceholder')}
          value={query}
          disabled={disabled}
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={activeId}
          aria-label={t('results.filterVarsLabel')}
          onChange={(event) => { setQuery(event.target.value); setShowAll(false); setActiveIndex(0); }}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') { event.preventDefault(); setActiveIndex((index) => Math.min(index + 1, shown.length - 1)); }
            else if (event.key === 'ArrowUp') { event.preventDefault(); setActiveIndex((index) => Math.max(index - 1, 0)); }
            else if (event.key === 'Enter' && shown.length > 0) { event.preventDefault(); toggleAt(Math.min(activeIndex, shown.length - 1)); }
            else if (event.key === 'Escape') { setQuery(''); setShowAll(false); }
          }}
        />
      </label>
      <ul id={listId} className="rv-vars" role="listbox" aria-label={t('results.pickVariables')}>
        {shown.map((v, index) => {
          const key = resultVariableKey(v);
          const selected = plotted.has(key);
          return (
            <li key={`${resultVariableKey(v)}:${index}`}>
              <button
                type="button"
                id={`${listId}-opt-${index}`}
                role="option"
                aria-selected={selected}
                className={`rv-var${selected ? ' active' : ''}${index === Math.min(activeIndex, shown.length - 1) ? ' focus' : ''}`}
                disabled={disabled}
                onClick={() => toggleAt(index)}
                onMouseEnter={() => setActiveIndex(index)}
                title={`${v.variable} · ${v.position} · ${formatUnit(v.unit)}`}
              >
                <span className="rv-var-name">{v.variable}</span>
                <span className="rv-var-pos">{v.position}</span>
                <span className="rv-var-unit" lang="en">{formatUnit(v.unit)}</span>
              </button>
            </li>
          );
        })}
      </ul>
      {total > shown.length && (
        <button type="button" className="rv-picker-more" onClick={() => setShowAll(true)} disabled={disabled}>
          {t('results.showMoreVars', { count: total - shown.length })}
        </button>
      )}
      {total === 0 && <p className="rv-picker-empty">{t('results.noMatchVars')}</p>}
    </div>
  );
}
