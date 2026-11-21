import { useId } from 'react';
import { displayText, toDisplay } from './displayQuantity.mjs';
import { formatUnit } from './formatUnit';
import { useLocale } from './i18n/index.ts';

type DisplayValueProps = {
  readonly value: number | string | null | undefined;
  readonly unit?: string | null;
  /** Approval cards show the OLGA value next to the shown one, and any other unit exactly as OLGA wrote it. */
  readonly withRaw?: boolean;
};

function numberOf(value: DisplayValueProps['value']): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value !== 'string' || value.trim() === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** A value in bar or °C when OLGA wrote it in Pa, K or C. The OLGA value and unit appear in a tip on
 *  hover and on keyboard focus. Text values and units the app does not convert pass through. */
export default function DisplayValue({ value, unit, withRaw = false }: DisplayValueProps) {
  const { t } = useLocale();
  const tipId = useId();
  const number = numberOf(value);
  const quantity = number === null ? null : toDisplay(number, unit);
  if (!quantity?.converted) {
    const shownUnit = unit ? (withRaw ? unit : formatUnit(unit)) : '';
    return <>{`${value ?? ''}${shownUnit ? ` ${shownUnit}` : ''}`}</>;
  }
  const raw = t('units.olgaRaw', { raw: `${value} ${String(unit ?? '').trim()}` });
  if (withRaw) {
    return <span className="display-value">{displayText(quantity)}<small className="display-value-raw">{raw}</small></span>;
  }
  return (
    <span className="display-value" tabIndex={0} aria-describedby={tipId}>
      {displayText(quantity)}
      <span className="display-value-tip" role="tooltip" id={tipId}>{raw}</span>
    </span>
  );
}
