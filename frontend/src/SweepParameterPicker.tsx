import { useEffect, useState } from 'react';
import { useLocale } from './i18n/index.ts';
import { fetchSweepParameters } from './sweepApi';
import type { SweepParameterOption } from './sweepApi';

type SweepParameterPickerProps = {
  readonly base: string | null;
  readonly value: string;
  readonly disabled: boolean;
  readonly onChange: (value: string) => void;
};

type CatalogState = 'idle' | 'loading' | 'ready' | 'unavailable';

export function SweepParameterPicker({
  base, value, disabled, onChange,
}: SweepParameterPickerProps) {
  const [parameters, setParameters] = useState<SweepParameterOption[]>([]);
  const [catalogState, setCatalogState] = useState<CatalogState>('idle');
  const { t } = useLocale();

  useEffect(() => {
    if (!base) {
      setParameters([]);
      setCatalogState('idle');
      return;
    }
    const controller = new AbortController();
    setCatalogState('loading');
    fetchSweepParameters(base, controller.signal)
      .then((nextParameters) => {
        setParameters(nextParameters);
        setCatalogState('ready');
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setParameters([]);
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
      <small id="sweep-parameter-guidance" aria-live="polite">{guidance}</small>
    </label>
  );
}
