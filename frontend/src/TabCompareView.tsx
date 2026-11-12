import { useState } from 'react';
import { useLocale } from './i18n/index.ts';

type MaxLocation = { pressure_pa: number; temperature_c: number };
type ColumnStat = {
  nodes: number;
  mean_rel_diff: number | null;
  max_rel_diff: number | null;
  max_location: MaxLocation | null;
  zero_reference_nodes: number;
  zero_reference_max_abs_diff: number;
};
type PresentStat = {
  scope: string;
  nodes: number;
  mean_rel_diff: number | null;
  max_rel_diff: number | null;
  max_location: MaxLocation | null;
};

const PHASE_LABEL_KEY: Record<string, string> = {
  gas_only: 'tabcompare.regionGasOnly',
  liquid_only: 'tabcompare.regionLiquidOnly',
  two_phase: 'tabcompare.regionTwoPhase',
};
const SCOPE_KEY: Record<string, string> = {
  gas: 'tabcompare.scopeGas',
  liquid: 'tabcompare.scopeLiquid',
  two_phase: 'tabcompare.scopeTwoPhase',
  all: 'tabcompare.scopeAll',
};

function asLocation(value: unknown): MaxLocation | null {
  const at = asRecord(value);
  const p = at ? asNumber(at['pressure_pa']) : null;
  const c = at ? asNumber(at['temperature_c']) : null;
  return p === null || c === null ? null : { pressure_pa: p, temperature_c: c };
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** A relative difference, or a dash when the column has none (every reference value was zero). */
function formatRel(value: number | null): string {
  if (value === null) return '—';
  if (value === 0) return '0';
  return value.toPrecision(3);
}

/** One axis value, or the range a binned heat cell covers. */
function span(bounds: unknown, fallback: unknown): string {
  if (Array.isArray(bounds)) {
    const low = asNumber(bounds[0]);
    const high = asNumber(bounds[1]);
    if (low !== null && high !== null) return low === high ? String(low) : `${low}–${high}`;
  }
  return String(fallback);
}

function heatLevel(value: number, peak: number): number {
  if (!(value > 0) || !(peak > 0)) return 0;
  return Math.min(4, Math.max(1, Math.ceil((4 * value) / peak)));
}

/** Read-only comparison of the owner's Multiflash table with the app engine
 *  table, rendered inside the tool result card in the dock. Numbers come from
 *  the fluids_compare_tab tool result; every heat cell duplicates a table
 *  value (cells are aria-hidden with titles, the strip carries an aria-label).
 */
export default function TabCompareView({ result }: { readonly result: Record<string, unknown> }) {
  const { locale, t } = useLocale();
  const [traceOpen, setTraceOpen] = useState(false);
  const columnsRecord = asRecord(result['columns']) ?? {};
  const names = Object.keys(columnsRecord).sort();
  const stats: Array<{ name: string; stat: ColumnStat }> = [];
  for (const name of names) {
    const entry = asRecord(columnsRecord[name]);
    if (!entry) continue;
    stats.push({
      name,
      stat: {
        nodes: asNumber(entry['nodes']) ?? 0,
        mean_rel_diff: asNumber(entry['mean_rel_diff']),
        max_rel_diff: asNumber(entry['max_rel_diff']),
        max_location: asLocation(entry['max_location']),
        zero_reference_nodes: asNumber(entry['zero_reference_nodes']) ?? 0,
        zero_reference_max_abs_diff: asNumber(entry['zero_reference_max_abs_diff']) ?? 0,
      },
    });
  }
  if (!stats.length) return <p>{t('tabcompare.noData') ?? 'No comparison data in this result.'}</p>;

  const grid = asRecord(result['grid']) ?? {};
  const method = grid['method'] === 'exact' ? t('tabcompare.methodExact') : t('tabcompare.methodCommon');
  const summary = locale === 'ko' ? result['summary_ko'] : result['summary_en'];
  const presentColumns = asRecord(asRecord(result['present_phase'])?.['columns']) ?? {};
  const present = new Map<string, PresentStat>();
  for (const [name, raw] of Object.entries(presentColumns)) {
    const entry = asRecord(raw);
    if (!entry) continue;
    present.set(name, {
      scope: typeof entry['scope'] === 'string' ? entry['scope'] : 'all',
      nodes: asNumber(entry['nodes']) ?? 0,
      mean_rel_diff: asNumber(entry['mean_rel_diff']),
      max_rel_diff: asNumber(entry['max_rel_diff']),
      max_location: asLocation(entry['max_location']),
    });
  }
  const hasPresent = present.size > 0;
  const headlineRaw = asRecord(asRecord(result['present_phase'])?.['headline']);
  const headline =
    hasPresent && headlineRaw && typeof headlineRaw['column'] === 'string' && asNumber(headlineRaw['max_rel_diff']) !== null
      ? {
          column: headlineRaw['column'],
          value: asNumber(headlineRaw['max_rel_diff']) as number,
          at: asLocation(headlineRaw['max_location']),
        }
      : null;
  const allPeak = stats.reduce<{ name: string; stat: ColumnStat } | null>(
    (best, item) =>
      item.stat.max_rel_diff !== null && (best === null || item.stat.max_rel_diff > (best.stat.max_rel_diff ?? -1))
        ? item
        : best,
    null,
  );
  const disagreement = asRecord(result['phase_disagreement']);
  const disagreeCount = asNumber(disagreement?.['count']) ?? 0;
  const disagreeNodes = (Array.isArray(disagreement?.['nodes']) ? (disagreement?.['nodes'] as unknown[]) : [])
    .map((entry) => asRecord(entry))
    .filter((entry): entry is Record<string, unknown> => entry !== null);
  const regions = asRecord(result['regions']) ?? {};
  const filled = asRecord(result['filled']) ?? {};
  const heat = asRecord(result['heat']);
  const heatPressures = Array.isArray(heat?.['pressures_pa']) ? (heat?.['pressures_pa'] as unknown[]) : [];
  const heatTemps = Array.isArray(heat?.['temperatures_c']) ? (heat?.['temperatures_c'] as unknown[]) : [];
  const heatColumns = asRecord(heat?.['columns']) ?? {};
  const heatPressureRanges = Array.isArray(heat?.['pressure_ranges_pa']) ? (heat?.['pressure_ranges_pa'] as unknown[]) : [];
  const heatTempRanges = Array.isArray(heat?.['temperature_ranges_c']) ? (heat?.['temperature_ranges_c'] as unknown[]) : [];
  const warnings = (Array.isArray(result['warnings']) ? (result['warnings'] as unknown[]) : [])
    .map((entry) => asRecord(entry))
    .map((entry) => (entry ? entry[locale === 'ko' ? 'message_ko' : 'message_en'] : null))
    .filter((text): text is string => typeof text === 'string' && text.length > 0);
  const skipped = Array.isArray(result['skipped_columns']) ? (result['skipped_columns'] as unknown[]) : [];
  const trace = result['trace'] ?? null;

  const regionRows = [
    { key: 'gas_only', label: t('tabcompare.regionGasOnly') },
    { key: 'liquid_only', label: t('tabcompare.regionLiquidOnly') },
    { key: 'two_phase', label: t('tabcompare.regionTwoPhase') },
  ];

  return (
    <div className="evidence-inspection tabcompare">
      <header className="inspection-head">
        <div>
          <span className="inspection-kicker">{t('tabcompare.kicker')}</span>
          <h4>{t('tabcompare.title')}</h4>
          <p>{typeof summary === 'string' && summary ? summary : ''}</p>
        </div>
        <strong>{t('tabcompare.regionNodes', { count: asNumber(result['compared_nodes']) ?? 0 })}</strong>
      </header>
      <p className="tabcompare-gridline">
        {t('tabcompare.gridLine', {
          compared: String(asNumber(result['compared_nodes']) ?? 0),
          reference: String(asNumber(grid['reference_nodes']) ?? 0),
          candidate: String(asNumber(grid['candidate_nodes']) ?? 0),
          method,
        })}
      </p>
      {warnings.map((text) => (
        <p key={text} className="tabcompare-warning" role="note">
          <strong>{t('tabcompare.warningLabel')}</strong> {text}
        </p>
      ))}
      {headline && (
        <p className="tabcompare-headline" data-testid="tabcompare-headline">
          {t('tabcompare.headline', {
            column: headline.column,
            value: formatRel(headline.value),
            at: headline.at
              ? t('tabcompare.nodeAt', {
                  p: String(headline.at.pressure_pa),
                  t: String(headline.at.temperature_c),
                })
              : '—',
          })}
        </p>
      )}
      {headline && allPeak && (
        <p className="tabcompare-headline-all" data-testid="tabcompare-headline-all">
          {t('tabcompare.headlineAll', {
            column: allPeak.name,
            value: formatRel(allPeak.stat.max_rel_diff),
          })}
        </p>
      )}
      {disagreeCount > 0 && (
        <section className="tabcompare-disagree" data-testid="tabcompare-phase-disagree" role="note">
          <p>
            <strong>{t('tabcompare.phaseDisagreeTitle', { count: disagreeCount })}</strong>
          </p>
          <ul>
            {disagreeNodes.map((node, index) => (
              <li key={index}>
                {t('tabcompare.phaseDisagreeNode', {
                  p: String(asNumber(node['pressure_pa']) ?? '—'),
                  t: String(asNumber(node['temperature_c']) ?? '—'),
                  reference: t(PHASE_LABEL_KEY[String(node['reference'])] ?? 'tabcompare.noData'),
                  candidate: t(PHASE_LABEL_KEY[String(node['candidate'])] ?? 'tabcompare.noData'),
                })}
              </li>
            ))}
          </ul>
          {disagreeCount > disagreeNodes.length && (
            <p>{t('tabcompare.phaseDisagreeMore', { count: disagreeCount - disagreeNodes.length })}</p>
          )}
        </section>
      )}
      <div className="evidence-table-viewport" tabIndex={0}>
        <table>
          <caption>{t('tabcompare.title')}</caption>
          <thead>
            <tr>
              <th scope="col">{t('tabcompare.column')}</th>
              {hasPresent && <th scope="col">{t('tabcompare.scope')}</th>}
              <th scope="col">{t('tabcompare.meanRel')}</th>
              <th scope="col">{t('tabcompare.maxRel')}</th>
              <th scope="col">{t('tabcompare.maxAt')}</th>
              {hasPresent && <th scope="col">{t('tabcompare.filledFigures')}</th>}
              <th scope="col">{t('tabcompare.zeroRef')}</th>
            </tr>
          </thead>
          <tbody>
            {stats.map(({ name, stat }) => {
              const own = present.get(name);
              const shown = own ?? stat;
              return (
              <tr key={name}>
                <th scope="row">{name}</th>
                {hasPresent && (
                  <td>
                    {own
                      ? `${t(SCOPE_KEY[own.scope] ?? 'tabcompare.scopeAll')} · ${t('tabcompare.regionNodes', { count: own.nodes })}`
                      : '—'}
                  </td>
                )}
                <td>{formatRel(shown.mean_rel_diff)}</td>
                <td>{formatRel(shown.max_rel_diff)}</td>
                <td>
                  {shown.max_location
                    ? t('tabcompare.nodeAt', {
                        p: String(shown.max_location.pressure_pa),
                        t: String(shown.max_location.temperature_c),
                      })
                    : '—'}
                </td>
                {hasPresent && (
                  <td data-testid={`tabcompare-filled-${name}`}>
                    {formatRel(stat.mean_rel_diff)} / {formatRel(stat.max_rel_diff)}
                  </td>
                )}
                <td data-testid={stat.zero_reference_nodes > 0 ? `tabcompare-zero-${name}` : undefined}>
                  {stat.zero_reference_nodes > 0
                    ? t('tabcompare.zeroRefCell', {
                        count: stat.zero_reference_nodes,
                        value: formatRel(stat.zero_reference_max_abs_diff),
                      })
                    : '—'}
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {hasPresent && <p className="tabcompare-heat-note">{t('tabcompare.presentNote')}</p>}
      <dl className="evidence-metrics tabcompare-regions" aria-label={t('tabcompare.regions')}>
        {regionRows.map(({ key, label }) => {
          const entry = asRecord(regions[key]);
          return (
            <div key={key}>
              <dt>{label}</dt>
              <dd>{t('tabcompare.regionNodes', { count: asNumber(entry?.['nodes']) ?? 0 })}</dd>
            </div>
          );
        })}
      </dl>
      <p className="tabcompare-filled">
        {t('tabcompare.filled')}: {t('tabcompare.filledReference')} [
        {Array.isArray(filled['reference']) && (filled['reference'] as unknown[]).length
          ? (filled['reference'] as unknown[]).join(', ')
          : t('tabcompare.filledNone')
        }] · {t('tabcompare.filledCandidate')} [
        {Array.isArray(filled['candidate']) && (filled['candidate'] as unknown[]).length
          ? (filled['candidate'] as unknown[]).join(', ')
          : t('tabcompare.filledNone')
        }]
      </p>
      {skipped.length > 0 && (
        <p className="tabcompare-skipped">{t('tabcompare.skipped', { list: skipped.join(', ') })}</p>
      )}
      <div className="tabcompare-heat-block">
        <h5>{t('tabcompare.heatTitle')}</h5>
        <p className="tabcompare-heat-note">{t('tabcompare.heatNote')}</p>
        {stats.map(({ name, stat }) => {
          const matrix = Array.isArray(heatColumns[name]) ? (heatColumns[name] as unknown[][]) : [];
          return (
            <section key={name} aria-label={name}>
              <h6>{name}</h6>
              <div
                className="tabcompare-heat"
                data-testid={`tabcompare-heat-${name}`}
                role="img"
                aria-label={t('tabcompare.heatAlt', { column: name, max: formatRel(stat.max_rel_diff) })}
                style={{ gridTemplateColumns: `repeat(${Math.max(heatTemps.length, 1)}, minmax(0, 1fr))` }}
              >
                {matrix.map((row, pi) =>
                  (Array.isArray(row) ? row : []).map((cell, ti) => {
                    const value = asNumber(cell);
                    const p = span(heatPressureRanges[pi], heatPressures[pi]);
                    const c = span(heatTempRanges[ti], heatTemps[ti]);
                    if (value === null) {
                      return (
                        <span
                          key={`${pi}-${ti}`}
                          className="tabcompare-heat-cell is-empty"
                          title={t('tabcompare.heatCellEmpty', { p, t: c })}
                          aria-hidden="true"
                        />
                      );
                    }
                    return (
                      <span
                        key={`${pi}-${ti}`}
                        className={`tabcompare-heat-cell is-b${heatLevel(value, stat.max_rel_diff ?? 0)}`}
                        title={t('tabcompare.heatCell', { p, t: c, value: formatRel(value) })}
                        aria-hidden="true"
                      />
                    );
                  }),
                )}
              </div>
            </section>
          );
        })}
      </div>
      <details
        className="evidence-audit tabcompare-trace"
        open={traceOpen}
        onToggle={(event) => setTraceOpen((event.target as HTMLDetailsElement).open)}
      >
        <summary>{traceOpen ? t('tabcompare.traceHide') : t('tabcompare.traceShow')}</summary>
        {trace === null || trace === undefined ? (
          <p>{t('tabcompare.traceEmpty')}</p>
        ) : (
          <pre>{JSON.stringify(trace, null, 2).slice(0, 6000)}</pre>
        )}
      </details>
    </div>
  );
}
