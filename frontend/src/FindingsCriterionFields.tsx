import GlossaryTerm from './GlossaryTerm';
import { useLocale } from './i18n/index.ts';
import type { I18nKey } from './i18n/ko.ts';
import { unitChoicesForDimension } from './unitPreferences';
import { formatUnit } from './formatUnit';

export type CriterionKind = 'pressure_drop' | 'liqc' | 'slugging' | 'wax_hydrate';

export type CriterionFieldKey =
  | 'inlet' | 'outlet' | 'maxDrop' | 'unit'
  | 'branch' | 'pipe' | 'maxCount' | 'hydrateTemp' | 'waxTemp' | 'maxLitres';

export const KIND_LABEL_KEYS: Readonly<Record<CriterionKind, I18nKey>> = {
  pressure_drop: 'findings.kind.pressure_drop',
  liqc: 'findings.kind.liqc',
  slugging: 'findings.kind.slugging',
  wax_hydrate: 'findings.kind.wax_hydrate',
};

function CatalogSelect({
  label, term, value, options, onChange,
}: {
  readonly label: string;
  readonly term: string;
  readonly value: string;
  readonly options: readonly string[];
  readonly onChange: (value: string) => void;
}) {
  const { t } = useLocale();
  return (
    <label className="findings-field">
      <span><GlossaryTerm term={term}>{label}</GlossaryTerm></span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">{t('findings.choose')}</option>
        {options.map((name) => <option key={name} value={name}>{name}</option>)}
      </select>
    </label>
  );
}

function NeutralNumber({
  label, term, value, onChange,
}: {
  readonly label: string;
  readonly term: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
}) {
  const { t } = useLocale();
  return (
    <label className="findings-field">
      <span><GlossaryTerm term={term}>{label}</GlossaryTerm></span>
      <input type="number" inputMode="decimal" placeholder={t('findings.numberPlaceholder')} value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

export default function FindingsCriterionFields({
  kind, glossaryTerm, positions, branchOptions, pipeOptions, values, variableUnit, onKindChange, onField,
}: {
  readonly kind: CriterionKind;
  readonly glossaryTerm: string;
  readonly positions: readonly string[];
  readonly branchOptions: readonly string[];
  readonly pipeOptions: readonly string[];
  readonly values: Readonly<Record<CriterionFieldKey, string>>;
  readonly variableUnit: string;
  readonly onKindChange: (kind: CriterionKind) => void;
  readonly onField: (key: CriterionFieldKey, value: string) => void;
}) {
  const { t } = useLocale();
  return (
    <>
      <label className="findings-field">
        <span><GlossaryTerm term={glossaryTerm}>{t('findings.criterion')}</GlossaryTerm></span>
        <select value={kind} onChange={(event) => onKindChange(event.target.value as CriterionKind)}>
          {(Object.keys(KIND_LABEL_KEYS) as CriterionKind[]).map((key) => (
            <option key={key} value={key}>{t(KIND_LABEL_KEYS[key])}</option>
          ))}
        </select>
      </label>

      {kind === 'pressure_drop' && (
        <>
          <CatalogSelect label={t('findings.field.inlet')} term={glossaryTerm} value={values.inlet} options={positions} onChange={(value) => onField('inlet', value)} />
          <CatalogSelect label={t('findings.field.outlet')} term={glossaryTerm} value={values.outlet} options={positions} onChange={(value) => onField('outlet', value)} />
          <NeutralNumber label={`${t('findings.field.maxDrop')} (${values.unit ? formatUnit(values.unit) : formatUnit(variableUnit)})`} term={glossaryTerm} value={values.maxDrop} onChange={(value) => onField('maxDrop', value)} />
          <label className="findings-field">
            <span><GlossaryTerm term={glossaryTerm}>{t('findings.field.unit')}</GlossaryTerm></span>
            <select value={values.unit} onChange={(event) => onField('unit', event.target.value)}>
              <option value="">{t('findings.choose')}</option>
              {unitChoicesForDimension('pressure').map((unit) => <option key={unit} value={unit}>{formatUnit(unit)}</option>)}
            </select>
          </label>
        </>
      )}

      {kind !== 'pressure_drop' && (
        <CatalogSelect label={t('findings.field.branch')} term={glossaryTerm} value={values.branch} options={branchOptions} onChange={(value) => onField('branch', value)} />
      )}

      {kind === 'slugging' && (
        <NeutralNumber label={t('findings.field.maxCount')} term={glossaryTerm} value={values.maxCount} onChange={(value) => onField('maxCount', value)} />
      )}

      {kind === 'wax_hydrate' && (
        <>
          <NeutralNumber label={`${t('findings.field.hydrateTemp')} (°C)`} term={glossaryTerm} value={values.hydrateTemp} onChange={(value) => onField('hydrateTemp', value)} />
          <NeutralNumber label={`${t('findings.field.waxTemp')} (°C)`} term={glossaryTerm} value={values.waxTemp} onChange={(value) => onField('waxTemp', value)} />
        </>
      )}

      {kind === 'liqc' && (
        <>
          <CatalogSelect label={t('findings.field.pipe')} term={glossaryTerm} value={values.pipe} options={pipeOptions} onChange={(value) => onField('pipe', value)} />
          <NeutralNumber label={`${t('findings.field.maxLitres')} (L)`} term={glossaryTerm} value={values.maxLitres} onChange={(value) => onField('maxLitres', value)} />
        </>
      )}
    </>
  );
}
