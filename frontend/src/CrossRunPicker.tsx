import type { ResultFile } from './resultContracts';
import { useLocale } from './i18n/index.ts';
import { runLabel } from './crossRunLabel.mjs';

/* Add the variable on screen from another run's result file. The hook refuses a unit or
   time-base mismatch and says why; nothing is converted to make two runs look alike. */
export function CrossRunPicker({ runs, variable, disabled, onPick }: {
  readonly runs: readonly ResultFile[];
  readonly variable: string | null;
  readonly disabled: boolean;
  readonly onPick: (file: ResultFile) => void;
}) {
  const { t, locale } = useLocale();
  if (runs.length === 0 || !variable) return null;
  return (
    <label className="rv-cross-run">
      <span>{t('overlay.otherRun', { variable })}</span>
      <select
        value=""
        disabled={disabled}
        onChange={(event) => {
          const file = runs.find((candidate) => candidate.id === event.target.value);
          if (file) onPick(file);
        }}
      >
        <option value="">{t('overlay.pickRun')}</option>
        {runs.map((file) => (
          <option key={file.id} value={file.id}>{runLabel(file, locale)}</option>
        ))}
      </select>
    </label>
  );
}
