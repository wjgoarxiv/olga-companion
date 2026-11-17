import { useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/index.ts';
import { ActivityLoader } from './ui/ActivityLoader';
import { OperationStatus } from './ui/OperationStatus';
import { Tabs } from './ui/Tabs';
import { createRequestEpoch } from './requestEpoch';
import { fetchTabGrid } from './tabGridApi';
import { formatBar, formatCell, heatLevels, type TabGrid } from './pvtGrid';
import { buildCurveChart, buildEnvelopeChart, CURVE_VIEW, hasEnvelope, type CurveChart } from './pvtCurves';

type View = 'table' | 'curves';

/** A bounded, scrollable value table with sticky axes; each cell is tinted by its place between the lowest and highest value. */
function ValueTable({ rowLabels, columnLabels, values, caption, corner, scrollAria }: {
  readonly rowLabels: readonly string[];
  readonly columnLabels: readonly string[];
  readonly values: readonly (readonly (number | null)[])[];
  readonly caption: string;
  readonly corner: string;
  readonly scrollAria: string;
}) {
  const levels = heatLevels(values.map((row) => [...row]));
  return (
    <div className="pvt-grid-viewport" tabIndex={0} aria-label={scrollAria}>
      <table className="pvt-grid-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            <th scope="col" className="pvt-grid-corner">{corner}</th>
            {columnLabels.map((label, ci) => <th key={ci} scope="col">{label}</th>)}
          </tr>
        </thead>
        <tbody>
          {values.map((row, pi) => (
            <tr key={pi}>
              <th scope="row">{rowLabels[pi]}</th>
              {row.map((value, ti) => (
                <td key={ti} className={levels[pi][ti] === null ? 'is-empty' : `is-b${levels[pi][ti]}`}>
                  {formatCell(value)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Axes({ chart, xTitle, yTitle }: {
  readonly chart: Pick<CurveChart, 'plot' | 'xTicks' | 'yTicks'>;
  readonly xTitle: string;
  readonly yTitle: string;
}) {
  const { plot } = chart;
  const middle = (plot.top + plot.bottom) / 2;
  return (
    <>
      {chart.yTicks.map((tick) => (
        <g key={`y${tick.value}`}>
          <line className="pvt-curve-grid" x1={plot.left} x2={plot.right} y1={tick.pos} y2={tick.pos} />
          <text className="pvt-curve-label" x={plot.left - 6} y={tick.pos} textAnchor="end" dominantBaseline="middle">{tick.label}</text>
        </g>
      ))}
      {chart.xTicks.map((tick) => (
        <text key={`x${tick.value}`} className="pvt-curve-label" x={tick.pos} y={plot.bottom + 18} textAnchor="middle">{tick.label}</text>
      ))}
      <line className="pvt-curve-axis" x1={plot.left} x2={plot.right} y1={plot.bottom} y2={plot.bottom} />
      <line className="pvt-curve-axis" x1={plot.left} x2={plot.left} y1={plot.top} y2={plot.bottom} />
      <text className="pvt-curve-title" x={(plot.left + plot.right) / 2} y={CURVE_VIEW.height - 6} textAnchor="middle">{xTitle}</text>
      <text className="pvt-curve-title" x={14} y={middle} textAnchor="middle" transform={`rotate(-90 14 ${middle})`}>{yTitle}</text>
    </>
  );
}

function LegendSwatch({ colorVar, dash }: { readonly colorVar: string; readonly dash: string }) {
  return (
    <svg width="28" height="10" aria-hidden="true">
      <line x1="0" x2="28" y1="5" y2="5" className="pvt-curve-line" style={{ stroke: `var(${colorVar})`, strokeDasharray: dash || undefined }} />
    </svg>
  );
}

/** The values of a .tab: one property as a pressure x temperature table or as curves against
 *  temperature, with the bubble/dew envelope when the file carries one. A legacy table (values
 *  per pressure and point, no temperature axis) is listed per pressure instead. */
export function PvtGridPreview({ path }: { readonly path: string }) {
  const { t } = useLocale();
  const [grid, setGrid] = useState<TabGrid | null>(null);
  const [column, setColumn] = useState<string | undefined>(undefined);
  const [view, setView] = useState<View>('table');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const requestRef = useRef(createRequestEpoch());

  useEffect(() => {
    const request = requestRef.current.begin();
    setLoading(true);
    setError('');
    fetchTabGrid(path, column)
      .then((next) => { if (requestRef.current.isCurrent(request)) setGrid(next); })
      .catch((cause) => {
        if (requestRef.current.isCurrent(request)) setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => { if (requestRef.current.isCurrent(request)) setLoading(false); });
    return () => requestRef.current.invalidate();
  }, [path, column]);

  if (error) {
    return <OperationStatus className="ws-operation-status" tone="error" title={t('pvtGrid.errorTitle')} detail={error} />;
  }
  if (!grid) return loading ? <ActivityLoader className="ws-loading" loadingLabel={t('pvtGrid.loading')} /> : null;

  const envelope = hasEnvelope(grid.envelope) ? grid.envelope : null;
  const legacy = grid.format === 'legacy' || !grid.values;
  const name = grid.column ?? '';
  const picker = (
    <div className="pvt-grid-bar">
      <label className="pvt-grid-pick">
        <span>{t('pvtGrid.property')}</span>
        <select value={name} onChange={(event) => setColumn(event.target.value)}>
          {grid.properties.map((property) => <option key={property} value={property}>{property}</option>)}
        </select>
      </label>
      <span className="pvt-grid-shape">
        {legacy
          ? t('pvtGrid.legacyShape', { p: grid.shape[0], n: grid.shape[1] })
          : t('pvtGrid.shape', { p: grid.shape[0], t: grid.shape[1] })}
        {grid.downsampled && !legacy ? ` · ${t('pvtGrid.sampled', { p: grid.pressures.length, t: grid.temperatures.length })}` : ''}
        {legacy && grid.unit ? ` · ${t('pvtGrid.legacyUnit', { unit: grid.unit })}` : ''}
      </span>
      {loading && <span className="pvt-grid-busy">{t('pvtGrid.loading')}</span>}
    </div>
  );

  let envelopePanel = null;
  if (envelope) {
    const chart = buildEnvelopeChart(envelope);
    envelopePanel = (
      <figure className="pvt-curve-figure">
        <svg viewBox={`0 0 ${CURVE_VIEW.width} ${CURVE_VIEW.height}`} role="img" aria-labelledby="pvt-env-title pvt-env-desc" preserveAspectRatio="xMidYMid meet">
          <title id="pvt-env-title">{t('pvtGrid.envTitle')}</title>
          <desc id="pvt-env-desc">{t('pvtGrid.envDesc')}</desc>
          <Axes chart={chart} xTitle={t('pvtGrid.axisT')} yTitle={t('pvtGrid.axisP')} />
          {chart.bubble && <path className="pvt-curve-line" d={chart.bubble} style={{ stroke: 'var(--pipe-1)' }} />}
          {chart.dew && <path className="pvt-curve-line" d={chart.dew} style={{ stroke: 'var(--pipe-2)', strokeDasharray: '7 3' }} />}
          {chart.critical && <circle className="pvt-curve-critical" cx={chart.critical.x} cy={chart.critical.y} r={5} />}
        </svg>
        <figcaption className="pvt-curve-legend">
          <span><LegendSwatch colorVar="--pipe-1" dash="" />{t('pvtGrid.envBubble')}</span>
          <span><LegendSwatch colorVar="--pipe-2" dash="7 3" />{t('pvtGrid.envDew')}</span>
          <span>
            <svg width="14" height="10" aria-hidden="true"><circle cx="7" cy="5" r="4" className="pvt-curve-critical" /></svg>
            {envelope.critical
              ? t('pvtGrid.envCriticalValue', { p: formatBar(envelope.critical.p_pa), t: formatCell(envelope.critical.t_c) })
              : t('pvtGrid.envCritical')}
          </span>
        </figcaption>
      </figure>
    );
  }

  if (legacy) {
    const points = grid.points ?? [];
    const indexes = grid.pointIndexes ?? (points[0] ?? []).map((_, i) => i);
    return (
      <section className="pvt-grid" aria-label={t('pvtGrid.aria', { column: name })}>
        {picker}
        <p className="pvt-grid-note" role="note">{t('pvtGrid.legacyNoTemperature')}</p>
        <ValueTable
          rowLabels={grid.pressures.map(formatBar)}
          columnLabels={indexes.map((i) => String(i + 1))}
          values={points}
          caption={t('pvtGrid.legacyCaption', { column: name })}
          corner={t('pvtGrid.legacyCorner')}
          scrollAria={t('pvtGrid.scrollAria')}
        />
        {envelopePanel}
      </section>
    );
  }

  const values = grid.values ?? [];
  const chart = view === 'curves' ? buildCurveChart(grid.pressures, grid.temperatures, values) : null;
  const drawn = chart ? chart.lines.filter((line) => line.points > 0) : [];
  return (
    <section className="pvt-grid" aria-label={t('pvtGrid.aria', { column: name })}>
      {picker}
      <Tabs
        ariaLabel={t('pvtGrid.viewTabs')}
        value={view}
        onChange={(next) => setView(next === 'curves' ? 'curves' : 'table')}
        items={[{ id: 'table', label: t('pvtGrid.viewTable') }, { id: 'curves', label: t('pvtGrid.viewCurves') }]}
      >
        {chart === null ? (
          <>
            <ValueTable
              rowLabels={grid.pressures.map(formatBar)}
              columnLabels={grid.temperatures.map(formatCell)}
              values={values}
              caption={t('pvtGrid.caption', { column: name })}
              corner={t('pvtGrid.corner')}
              scrollAria={t('pvtGrid.scrollAria')}
            />
            <p className="pvt-grid-note">{t('pvtGrid.tintNote')}</p>
          </>
        ) : drawn.length === 0 ? (
          <p className="pvt-grid-note" role="note">{t('pvtGrid.curveNoData')}</p>
        ) : (
          <figure className="pvt-curve-figure">
            <svg viewBox={`0 0 ${CURVE_VIEW.width} ${CURVE_VIEW.height}`} role="img" aria-labelledby="pvt-curve-title pvt-curve-desc" preserveAspectRatio="xMidYMid meet">
              <title id="pvt-curve-title">{t('pvtGrid.curveTitle', { column: name })}</title>
              <desc id="pvt-curve-desc">
                {t('pvtGrid.curveDesc', { count: drawn.length, low: formatBar(drawn[0].pressurePa), high: formatBar(drawn[drawn.length - 1].pressurePa) })}
              </desc>
              <Axes chart={chart} xTitle={t('pvtGrid.axisT')} yTitle={name} />
              {drawn.map((line) => (
                <path key={line.pressureIndex} className="pvt-curve-line" d={line.d} style={{ stroke: `var(${line.colorVar})`, strokeDasharray: line.dash || undefined }} />
              ))}
            </svg>
            <figcaption className="pvt-curve-legend">
              {drawn.map((line) => (
                <span key={line.pressureIndex}>
                  <LegendSwatch colorVar={line.colorVar} dash={line.dash} />
                  {t('pvtGrid.legendPressure', { p: formatBar(line.pressurePa) })}
                </span>
              ))}
            </figcaption>
            <p className="pvt-grid-note">{t('pvtGrid.curveNote')}</p>
          </figure>
        )}
      </Tabs>
      {envelopePanel}
    </section>
  );
}
