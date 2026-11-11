import type { ConversionMetadata, Series, SeriesRangeSpec, SeriesViewSpec } from './session';
import { useLocale } from './i18n/index.ts';
import type { I18nKey, TranslateFn } from './i18n/index.ts';
import { unitChoicesForDimension } from './unitPreferences';

type CalibrationRailProps = {
  readonly series: Series;
  readonly view: SeriesViewSpec;
  readonly disabled: boolean;
  readonly onChange: (view: SeriesViewSpec) => void;
};

type RangeId = 'full' | 'tail25' | 'tail10';

const RANGE_OPTIONS: readonly { id: RangeId; value: SeriesRangeSpec }[] = [
  { id: 'full', value: { mode: 'full' } },
  { id: 'tail25', value: { mode: 'tail', fraction: 0.25 } },
  { id: 'tail10', value: { mode: 'tail', fraction: 0.1 } },
];

const RANGE_LABEL_KEYS: Readonly<Record<RangeId, I18nKey>> = {
  full: 'calib.rangeFull',
  tail25: 'calib.rangeTail25',
  tail10: 'calib.rangeTail10',
};

function reasonLabel(conversion: ConversionMetadata, t: TranslateFn): string {
  switch (conversion.reason) {
    case 'explicit_pressure_reference_requires_metadata':
      return t('calib.reasonExplicit');
    case 'unknown_source_unit':
      return t('calib.reasonUnknownSource');
    case 'unknown_requested_unit':
      return t('calib.reasonUnknownTarget');
    case 'incompatible_dimensions':
      return t('calib.reasonIncompatible');
    default:
      return conversion.status === 'source_only' ? t('calib.reasonSourceOnly') : '';
  }
}

function rangeSelected(current: SeriesRangeSpec, candidate: SeriesRangeSpec): boolean {
  if (current.mode !== candidate.mode) return false;
  if (current.mode === 'tail' && candidate.mode === 'tail') return current.fraction === candidate.fraction;
  if (current.mode === 'bounds' && candidate.mode === 'bounds') return current.start === candidate.start && current.end === candidate.end;
  return true;
}

export default function CalibrationRail({ series, view, disabled, onChange }: CalibrationRailProps) {
  const { t } = useLocale();
  const valueConversion = series.view.value_conversion;
  const timeConversion = series.view.time_conversion;
  const valueChoices = unitChoicesForDimension(valueConversion.dimension);
  const timeChoices = unitChoicesForDimension('time');
  const emittedValueUnit = valueConversion.output_unit || series.unit || valueConversion.source_unit || t('calib.unitUnavailable');
  const emittedTimeUnit = timeConversion.output_unit || series.time_unit || timeConversion.source_unit || t('calib.unitUnavailable');
  const valueLocked = valueConversion.status === 'source_only' || !valueConversion.dimension || valueChoices.length === 0;
  const timeLocked = timeConversion.status === 'source_only' || timeConversion.dimension !== 'time';
  const temperature = valueConversion.dimension === 'temperature';
  const valueReason = reasonLabel(valueConversion, t);
  const timeReason = reasonLabel(timeConversion, t);
  const conversionReasons = [valueReason, timeReason].filter((reason, index, all) => reason && all.indexOf(reason) === index);

  return (
    <section className="calibration-rail" aria-label={t('calib.rail')}>
      <div className="calibration-title">
        <span>{t('calib.rail')}</span>
        <span className="calibration-source">{t('calib.source')} · {valueConversion.source_unit || t('calib.noUnit')} · {t('calib.timeLabel')} {timeConversion.source_unit || t('calib.noUnit')}</span>
      </div>

      <label className="calibration-field">
        <span>{t('calib.valueUnit')}</span>
        <select
          value={emittedValueUnit}
          disabled={disabled || valueLocked}
          onChange={(event) => onChange({ ...view, value_unit: event.target.value })}
        >
          {valueLocked ? <option value={emittedValueUnit}>{t('calib.sourceLocked', { unit: emittedValueUnit })}</option> : valueChoices.map((unit) => <option key={unit} value={unit}>{unit}</option>)}
        </select>
      </label>

      <label className="calibration-field">
        <span>{t('calib.timeUnit')}</span>
        <select
          value={emittedTimeUnit}
          disabled={disabled || timeLocked}
          onChange={(event) => onChange({ ...view, time_unit: event.target.value })}
        >
          {timeLocked ? <option value={emittedTimeUnit}>{t('calib.sourceLocked', { unit: emittedTimeUnit })}</option> : timeChoices.map((unit) => <option key={unit} value={unit}>{unit}</option>)}
        </select>
      </label>

      <fieldset className="calibration-segment">
        <legend>{t('calib.range')}</legend>
        <div>
          {RANGE_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              aria-pressed={rangeSelected(view.range, option.value)}
              disabled={disabled}
              onClick={() => onChange({ ...view, range: option.value })}
            >
              {t(RANGE_LABEL_KEYS[option.id])}
            </button>
          ))}
        </div>
      </fieldset>

      {temperature && (
        <fieldset className="calibration-segment calibration-meaning">
          <legend>{t('calib.tempMeaning')}</legend>
          <div>
            <button type="button" aria-pressed={view.quantity_kind === 'point'} disabled={disabled} onClick={() => onChange({ ...view, quantity_kind: 'point' })}>{t('calib.tempPoint')}</button>
            <button type="button" aria-pressed={view.quantity_kind === 'delta'} disabled={disabled} onClick={() => onChange({ ...view, quantity_kind: 'delta' })}>{t('calib.tempDelta')}</button>
          </div>
        </fieldset>
      )}

      {conversionReasons.length > 0 && (
        <p className="calibration-reason" role="status">{conversionReasons.join(' ')}</p>
      )}
    </section>
  );
}
