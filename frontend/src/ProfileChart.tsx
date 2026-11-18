import { useId, useMemo } from 'react';
import type { Profile } from './resultApi';
import { formatDistinctTicks, formatSignificant } from './significantFigures.mjs';
import { niceTicks, ticksWithin } from './trendGeometry';
import { formatUnit } from './formatUnit';
import { useMeasuredWidth, yAxisMargin } from './useMeasuredWidth';
import { useLocale } from './i18n/index.ts';
import { useSignificantFigures } from './useSignificantFigures';

/* Spatial profile view for .ppl results: distance along the branch on x,
 * the selected variable on y. Trends answer "how does this point change over
 * time"; this answers "how is this distributed along the branch right now". */

const DEFAULT_WIDTH = 920;
const MIN_WIDTH = 360;
const TICK_FONT_PX = 12;

function ticks(minimum: number, maximum: number, count: number): number[] {
  return ticksWithin(niceTicks(minimum, maximum, count), minimum, maximum);
}

type ProfileChartProps = {
  readonly profile: Profile;
};

export default function ProfileChart({ profile }: ProfileChartProps) {
  const significantFigures = useSignificantFigures();
  const { t } = useLocale();
  const titleId = useId();
  const descriptionId = useId();
  const { width: W, setElement } = useMeasuredWidth(MIN_WIDTH, DEFAULT_WIDTH);
  const H = Math.min(380, Math.max(280, Math.round(W * 0.37)));

  const geometry = useMemo(() => {
    const positions = profile.positions.filter((value) => Number.isFinite(value));
    const values = profile.values.filter((value) => Number.isFinite(value));
    if (positions.length === 0 || positions.length !== values.length) return null;
    const xMin = Math.min(...positions);
    const xMax = Math.max(...positions);
    const yMin = Math.min(...values);
    const yMax = Math.max(...values);
    // A constant profile still deserves a readable band rather than a flat edge.
    const ySpan = yMax - yMin || Math.max(Math.abs(yMax) * 0.02, 1e-9);
    const yLow = yMax === yMin ? yMin - ySpan : yMin;
    const yHigh = yMax === yMin ? yMax + ySpan : yMax;
    const xSpan = xMax - xMin || 1;
    const yTickValues = ticks(yLow, yHigh, 4);
    const xTickValues = ticks(xMin, xMax, 5);
    const yLabels = formatDistinctTicks(yTickValues, significantFigures);
    const xLabels = formatDistinctTicks(xTickValues, significantFigures);
    const longestYLabel = Math.max(...yLabels.map((label) => label.length));
    const M = { l: yAxisMargin(longestYLabel, TICK_FONT_PX, 76), r: 24, t: 18, b: 48 };
    const IW = W - M.l - M.r;
    const IH = H - M.t - M.b;
    const toX = (value: number) => M.l + ((value - xMin) / xSpan) * IW;
    const toY = (value: number) => M.t + IH - ((value - yLow) / (yHigh - yLow)) * IH;
    const points = positions.map((position, index) => ({
      x: toX(position),
      y: toY(values[index]),
      position,
      value: values[index],
    }));
    return {
      points,
      path: points.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(' '),
      xTicks: xTickValues.map((value, index) => ({ value, label: xLabels[index], x: toX(value) })),
      yTicks: yTickValues.map((value, index) => ({ value, label: yLabels[index], y: toY(value) })),
      M, IW, IH,
    };
  }, [profile, W, H, significantFigures]);

  if (!geometry) {
    return <p className="ws-empty">{t('profile.noSamples')}</p>;
  }

  const { M, IW, IH } = geometry;
  const unit = profile.unit ? ` (${formatUnit(profile.unit)})` : '';
  const at = profile.timestep === null || profile.timestep === undefined
    ? ''
    : t('profile.atTime', { time: formatSignificant(profile.timestep, significantFigures), unit: profile.timestep_unit ?? 's' }) ?? ` at ${formatSignificant(profile.timestep, significantFigures)} ${profile.timestep_unit ?? 's'}`;

  return (
    <figure className="profile-chart">
      <svg
        ref={setElement}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-labelledby={`${titleId} ${descriptionId}`}
        preserveAspectRatio="xMidYMid meet"
      >
        <title id={titleId}>{t('profile.chartTitle', { variable: profile.variable, branch: profile.branch }) ?? `${profile.variable} along ${profile.branch}`}</title>
        <desc id={descriptionId}>
          {t('profile.chartDesc', { count: geometry.points.length, from: formatSignificant(geometry.points[0].position, significantFigures), to: formatSignificant(geometry.points[geometry.points.length - 1].position, significantFigures), at }) ?? `${geometry.points.length} samples from ${formatSignificant(geometry.points[0].position, significantFigures)} to ${formatSignificant(geometry.points[geometry.points.length - 1].position, significantFigures)} m${at}.`}
        </desc>
        {geometry.yTicks.map((tick) => (
          <g key={`y${tick.value}`}>
            <line className="profile-grid" x1={M.l} x2={M.l + IW} y1={tick.y} y2={tick.y} />
            <text className="profile-axis-label" x={M.l - 10} y={tick.y} textAnchor="end" dominantBaseline="middle">
              {tick.label}
            </text>
          </g>
        ))}
        {geometry.xTicks.map((tick) => (
          <text
            key={`x${tick.value}`}
            className="profile-axis-label"
            x={tick.x}
            y={M.t + IH + 22}
            textAnchor="middle"
          >
            {tick.label}
          </text>
        ))}
        <line className="profile-axis" x1={M.l} x2={M.l + IW} y1={M.t + IH} y2={M.t + IH} />
        <line className="profile-axis" x1={M.l} x2={M.l} y1={M.t} y2={M.t + IH} />
        <path className="profile-line" d={geometry.path} fill="none" />
        {geometry.points.map((point) => (
          <circle key={`${point.position}`} className="profile-point" cx={point.x} cy={point.y} r={2.5} />
        ))}
        <text className="profile-axis-title" x={M.l + IW / 2} y={H - 8} textAnchor="middle">
          {t('profile.axisX')}
        </text>
        <text
          className="profile-y-title"
          x={14}
          y={M.t + IH / 2}
          textAnchor="middle"
          transform={`rotate(-90 14 ${M.t + IH / 2})`}
        >
          {t('profile.yAxis', { variable: profile.variable, unit: formatUnit(profile.unit ?? '') })}
        </text>
      </svg>
      <figcaption className="profile-caption">
        {t('profile.caption', { variable: profile.variable, unit, branch: profile.branch, at, count: geometry.points.length }) ?? `${profile.variable}${unit} · ${profile.branch}${at} · ${geometry.points.length} samples`}
      </figcaption>
    </figure>
  );
}
