import { useEffect, useState } from 'react';
import { useLocale, type TranslateFn } from './i18n/index.ts';
import { fetchSweepParameters } from './sweepApi';
import type { SweepParameterOption } from './sweepApi';

type SweepParameterPickerProps = {
  readonly base: string | null;
  readonly value: string;
  readonly disabled: boolean;
  readonly onChange: (value: string) => void;
};

type CatalogState = 'idle' | 'loading' | 'ready' | 'unavailable';

const AMBIGUOUS_SHOWN = 5;

/** The repeated keys the catalog leaves out: the first few by name, then how many more. */
export function ambiguousGuide(t: TranslateFn, names: readonly string[]): string {
  if (names.length === 0) return '';
  const shown = names.slice(0, AMBIGUOUS_SHOWN).join(', ');
  const rest = names.length - AMBIGUOUS_SHOWN;
  return t('sweep.guideAmbiguous', {
    count: names.length,
    names: rest > 0 ? `${shown} ${t('sweep.guideAmbiguousMore', { count: rest })}` : shown,
  });
}

export function SweepParameterPicker({
  base, value, disabled, onChange,
}: SweepParameterPickerProps) {
  const [parameters, setParameters] = useState<SweepParameterOption[]>([]);
  const [ambiguous, setAmbiguous] = useState<string[]>([]);
  const [catalogState, setCatalogState] = useState<CatalogState>('idle');
  const { t } = useLocale();

  useEffect(() => {
    if (!base) {
      setParameters([]);
      setAmbiguous([]);
      setCatalogState('idle');
      return;
    }
    const controller = new AbortController();
    setCatalogState('loading');
    fetchSweepParameters(base, controller.signal)
      .then((catalog) => {
        setParameters(catalog.parameters);
        setAmbiguous(catalog.ambiguous);
        setCatalogState('ready');
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setParameters([]);
        setAmbiguous([]);
        setCatalogState('unavailable');
      });
    return () => controller.abort();
  }, [base]);

  const guidance = catalogState === 'loading'
    ? t('sweep.guideLoading') ?? 'Reading parameters from the active case…'
    : catalogState === 'ready'
      ? t('sweep.guideReady', { count: parameters.length }) ?? `${parameters.length} unique case parameters available. Manual GENKEY path entry remains available.`
      : catalogState === 'unavailable'
        ? t('sweep.guideUnavailable') ?? 'Case catalog unavailable. Manual GENKEY path entry remains available.'
        : t('sweep.guideIdle') ?? 'Select an active case or enter a GENKEY path manually.';

  return (
    <label className="sweep-parameter-field">
      <span>{t('sweep.paramKey')}</span>
      <input
        className="rv-filter sweep-input"
        aria-label={t('sweep.paramAria')}
        aria-describedby="sweep-parameter-guidance"
        list="sweep-parameter-options"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
      <datalist id="sweep-parameter-options">
        {parameters.map((parameter) => (
          <option key={parameter.path} value={parameter.path}>{parameter.keyword} · {parameter.key}</option>
        ))}
      </datalist>
      <small id="sweep-parameter-guidance" aria-live="polite">
        {guidance}
        {catalogState === 'ready' && ambiguous.length > 0 && ` ${ambiguousGuide(t, ambiguous)}`}
      </small>
    </label>
  );
}
