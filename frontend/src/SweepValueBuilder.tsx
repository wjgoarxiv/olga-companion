import { useState } from 'react';
import { useLocale } from './i18n/index.ts';
import { buildRangeSweepValues, MAX_SWEEP_CASES, readRangeSweepValues, splitSweepValues } from './sweepValueGrammar';

type SweepValueMode = 'range' | 'list';

type SweepValueBuilderProps = {
  readonly value: string;
  readonly disabled: boolean;
  readonly onChange: (value: string) => void;
};

const VALUE_MODES: readonly { readonly id: SweepValueMode; readonly labelKey: 'sweep.modeRange' | 'sweep.modeList' }[] = [
  { id: 'range', labelKey: 'sweep.modeRange' },
  { id: 'list', labelKey: 'sweep.modeList' },
];

export function SweepValueBuilder({ value, disabled, onChange }: SweepValueBuilderProps) {
  const { t } = useLocale();
  const initialRange = readRangeSweepValues(value, { start: 3600, stop: 7200, count: 2, unit: '' });
  const [mode, setMode] = useState<SweepValueMode>('range');
  const [start, setStart] = useState(initialRange.start);
  const [stop, setStop] = useState(initialRange.stop);
  const [count, setCount] = useState(initialRange.count);
  const [unit, setUnit] = useState(initialRange.unit);
  const [draft, setDraft] = useState('');
  const values = splitSweepValues(value);

  const commitRange = (nextStart: number, nextStop: number, nextCount: number, nextUnit: string) => {
    const next = buildRangeSweepValues({ start: nextStart, stop: nextStop, count: nextCount, unit: nextUnit });
    if (next) onChange(next);
  };

  const addValue = () => {
    const nextValue = draft.trim();
    if (!nextValue || values.length >= MAX_SWEEP_CASES) return;
    onChange([...values, nextValue].join(','));
    setDraft('');
  };

  const selectMode = (nextMode: SweepValueMode) => {
    switch (nextMode) {
      case 'list':
        setMode(nextMode);
        return;
      case 'range': {
        const nextRange = readRangeSweepValues(value, { start, stop, count, unit });
        setStart(nextRange.start);
        setStop(nextRange.stop);
        setCount(nextRange.count);
        setUnit(nextRange.unit);
        setMode(nextMode);
        return;
      }
      default: {
        const unreachable: never = nextMode;
        throw new RangeError(`Unsupported sweep value mode: ${unreachable}`);
      }
    }
  };

  return (
    <div className="sweep-value-builder">
      <div className="sweep-value-mode" role="group" aria-label={t('sweep.modeAria')}>
        {VALUE_MODES.map((option) => (
          <button
            key={option.id}
            type="button"
            aria-pressed={mode === option.id}
            disabled={disabled}
            onClick={() => selectMode(option.id)}
          >
            {t(option.labelKey)}
          </button>
        ))}
      </div>

      {mode === 'range' ? (
        <div className="sweep-range-grid">
          <label>
            <span>{t('sweep.rangeStart') ?? 'Start'}</span>
            <input type="number" value={start} disabled={disabled} onChange={(event) => {
              const next = event.target.valueAsNumber;
              if (!Number.isFinite(next)) return;
              setStart(next);
              commitRange(next, stop, count, unit);
            }} />
          </label>
          <label>
            <span>{t('sweep.rangeStop') ?? 'Stop'}</span>
            <input type="number" value={stop} disabled={disabled} onChange={(event) => {
              const next = event.target.valueAsNumber;
              if (!Number.isFinite(next)) return;
              setStop(next);
              commitRange(start, next, count, unit);
            }} />
          </label>
          <label>
            <span>{t('sweep.rangeCases') ?? 'Cases'}</span>
            <input type="number" min="2" max={MAX_SWEEP_CASES} step="1" value={count} disabled={disabled} onChange={(event) => {
              const requested = event.target.valueAsNumber;
              if (!Number.isFinite(requested)) return;
              const next = Math.max(2, Math.min(MAX_SWEEP_CASES, Math.round(requested)));
              setCount(next);
              commitRange(start, stop, next, unit);
            }} />
          </label>
          <label>
            <span>{t('sweep.unitOptional') ?? 'Unit · optional'}</span>
            <input list="sweep-unit-options" value={unit} disabled={disabled} placeholder={t('sweep.unitPlaceholder') ?? 's, bar, °C…'} onChange={(event) => {
              const next = event.target.value;
              setUnit(next);
              commitRange(start, stop, count, next);
            }} />
            <datalist id="sweep-unit-options">
              {['s', 'min', 'h', 'Pa', 'bar', 'K', '°C', 'm', 'kg/s'].map((option) => <option key={option} value={option} />)}
            </datalist>
          </label>
        </div>
      ) : (
        <div className="sweep-list-editor">
          <div className="sweep-value-chips" aria-label={t('sweep.valuesAria', { count: values.length }) ?? `${values.length} sweep values`}>
            {values.map((item, index) => (
              <span className="sweep-value-chip" key={`${item}-${index}`}>
                {item}
                <button type="button" aria-label={t('sweep.removeValue', { item }) ?? `Remove ${item}`} disabled={disabled} onClick={() => onChange(values.filter((_, itemIndex) => itemIndex !== index).join(','))}>×</button>
              </span>
            ))}
          </div>
          <div className="sweep-value-add">
            <input
              value={draft}
              disabled={disabled || values.length >= MAX_SWEEP_CASES}
              aria-label="Add sweep value"
              placeholder={t('sweep.addValuePlaceholder') ?? 'Type a value with unit'}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  addValue();
                }
              }}
            />
            <button type="button" disabled={disabled || !draft.trim() || values.length >= MAX_SWEEP_CASES} onClick={addValue}>{t('sweep.addButton') ?? 'Add'}</button>
          </div>
        </div>
      )}

      <div className="sweep-value-preview" aria-live="polite">
        <strong>{t('sweep.valueCount', { count: values.length })}</strong>
        <span>{values.join('  ·  ') || (t('sweep.emptyHint') ?? 'Add at least one value')}</span>
      </div>
    </div>
  );
}
