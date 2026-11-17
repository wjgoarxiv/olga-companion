import type { Series, SeriesViewSpec } from './session';
import { useLocale } from './i18n/index.ts';
import { matchUnitChoice, unitChoicesForDimension } from './unitPreferences';

type ChartUnitBarProps = {
  readonly series: Series;
  readonly view: SeriesViewSpec;
  readonly valueLabel: string;
  readonly disabled: boolean;
  readonly onChange: (view: SeriesViewSpec) => void;
};

/* Axis units, directly above the chart: the y-axis variable and its unit on the
 * left, time and its unit on the right. A unit outside the conversion registry
 * stays shown but locked; the rail below says why. */
export default function ChartUnitBar({ series, view, valueLabel, disabled, onChange }: ChartUnitBarProps) {
  const { t } = useLocale();
  const valueConversion = series.view.value_conversion;
  const timeConversion = series.view.time_conversion;
  const valueChoices = unitChoicesForDimension(valueConversion.dimension);
  const timeChoices = unitChoicesForDimension('time');
  const valueUnit = valueConversion.output_unit || series.unit || valueConversion.source_unit || t('calib.unitUnavailable');
  const timeUnit = timeConversion.output_unit || series.time_unit || timeConversion.source_unit || t('calib.unitUnavailable');
  const valueSelected = matchUnitChoice(valueChoices, valueUnit);
  const timeSelected = matchUnitChoice(timeChoices, timeUnit);
  const valueLocked = valueConversion.status === 'source_only' || !valueConversion.dimension || valueSelected === null;
  const timeLocked = timeConversion.status === 'source_only' || timeConversion.dimension !== 'time' || timeSelected === null;

  return (
    <div className="chart-unit-bar" role="group" aria-label={t('chartUnits.aria')}>
      <label className="chart-unit chart-unit-y">
        <span className="chart-unit-axis">{valueLabel}</span>
        <select
          aria-label={t('calib.valueUnit')}
          value={valueSelected ?? valueUnit}
          disabled={disabled || valueLocked}
          onChange={(event) => onChange({ ...view, value_unit: event.target.value })}
        >
          {valueLocked ? <option value={valueSelected ?? valueUnit}>{t('calib.sourceLocked', { unit: valueUnit })}</option> : valueChoices.map((unit) => <option key={unit} value={unit}>{unit}</option>)}
        </select>
      </label>
      <label className="chart-unit chart-unit-x">
        <span className="chart-unit-axis">{t('calib.timeLabel')}</span>
        <select
          aria-label={t('calib.timeUnit')}
          value={timeSelected ?? timeUnit}
          disabled={disabled || timeLocked}
          onChange={(event) => onChange({ ...view, time_unit: event.target.value })}
        >
          {timeLocked ? <option value={timeSelected ?? timeUnit}>{t('calib.sourceLocked', { unit: timeUnit })}</option> : timeChoices.map((unit) => <option key={unit} value={unit}>{unit}</option>)}
        </select>
      </label>
    </div>
  );
}
