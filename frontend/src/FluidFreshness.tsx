import { useLocale } from './i18n/index.ts';
import type { FluidFreshnessRow } from './runContracts';

/* One fact per found fluid table on the run preview: fresh (matches its .mfl), stale (the
 * .mfl changed after the table was made) or unknown (no usable record). Unknown keeps the
 * plain tone so it never reads as either of the other two. */
export function FluidFreshnessFacts({ rows }: { readonly rows: readonly FluidFreshnessRow[] }) {
  const { t } = useLocale();
  return (
    <>
      {rows.map((row) => {
        const mfl = row.mfl ?? '';
        const text = row.state === 'fresh'
          ? t('run.fluidFresh', { mfl })
          : row.state === 'stale'
            ? t('run.fluidStale', { mfl })
            : t(`run.fluidUnknown.${row.reason}`, { mfl });
        return (
          <span key={row.reference} className="run-fluid-fact" data-state={row.state}>
            <strong>{t('run.fluidTable', { name: row.reference })}</strong>
            <em className={row.state === 'fresh' ? 'pass' : row.state === 'stale' ? 'warn' : undefined}>{text}</em>
          </span>
        );
      })}
    </>
  );
}
