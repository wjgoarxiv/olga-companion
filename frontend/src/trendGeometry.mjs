function finitePair(time, values, index) {
  return Number.isFinite(time[index]) && Number.isFinite(values[index]);
}

function coordinate(value) {
  return Number.isFinite(value) ? Number(value.toFixed(2)) : 0;
}

function collectFinitePoints(time, values) {
  const count = Math.min(time.length, values.length);
  const points = [];
  let segment = -1;
  let previousWasFinite = false;
  for (let index = 0; index < count; index += 1) {
    if (!finitePair(time, values, index)) {
      previousWasFinite = false;
      continue;
    }
    if (!previousWasFinite) segment += 1;
    points.push({ index, time: time[index], value: values[index], segment });
    previousWasFinite = true;
  }
  return points;
}

export function createInspectionNavigation(time, values) {
  const indices = [];
  const ordinalByIndex = new Map();
  const count = Math.min(time.length, values.length);
  for (let index = 0; index < count; index += 1) {
    if (finitePair(time, values, index)) {
      ordinalByIndex.set(index, indices.length);
      indices.push(index);
    }
  }
  return { indices, ordinalByIndex };
}

export function transitionInspection(key, currentIndex, navigation) {
  const { indices, ordinalByIndex } = navigation;
  const lastOrdinal = indices.length - 1;
  const currentOrdinal = currentIndex == null ? null : ordinalByIndex.get(currentIndex) ?? null;
  switch (key) {
    case 'ArrowLeft':
      return { handled: true, nextIndex: indices[currentOrdinal == null ? lastOrdinal : Math.max(0, currentOrdinal - 1)] ?? null };
    case 'ArrowRight':
      return { handled: true, nextIndex: indices[currentOrdinal == null ? 0 : Math.min(lastOrdinal, currentOrdinal + 1)] ?? null };
    case 'Home':
      return { handled: true, nextIndex: indices[0] ?? null };
    case 'End':
      return { handled: true, nextIndex: indices[lastOrdinal] ?? null };
    case 'Escape':
      return { handled: true, nextIndex: null };
    default:
      return { handled: false, nextIndex: currentIndex };
  }
}

export function finiteSampleOrdinal(index, navigation) {
  const ordinal = navigation.ordinalByIndex.get(index);
  return ordinal === undefined ? null : ordinal + 1;
}

function retainMinMax(points, pointBudget) {
  if (points.length <= pointBudget * 2 + 2) return points;
  const retained = new Map();
  const remember = (point) => retained.set(point.index, point);
  remember(points[0]);
  remember(points[points.length - 1]);

  const buckets = Math.max(1, Math.floor(pointBudget));
  for (let bucket = 0; bucket < buckets; bucket += 1) {
    const start = Math.floor((bucket * points.length) / buckets);
    const end = Math.floor(((bucket + 1) * points.length) / buckets);
    if (start >= end) continue;
    let minimum = points[start];
    let maximum = points[start];
    for (let index = start + 1; index < end; index += 1) {
      const point = points[index];
      if (point.value < minimum.value) minimum = point;
      if (point.value > maximum.value) maximum = point;
    }
    remember(minimum);
    remember(maximum);
  }
  return [...retained.values()].sort((left, right) => left.index - right.index);
}

export function buildTrendGeometry(time, values, options = {}) {
  const width = Number.isFinite(options.width) && options.width > 0 ? options.width : 1;
  const height = Number.isFinite(options.height) && options.height > 0 ? options.height : 1;
  const pointBudget = Number.isFinite(options.pointBudget) && options.pointBudget > 0
    ? Math.max(1, Math.floor(options.pointBudget))
    : Math.max(1, Math.floor(width));
  const finite = collectFinitePoints(time, values);
  if (finite.length === 0) {
    return {
      points: [],
      path: '',
      xDomain: null,
      yDomain: null,
      finiteCount: 0,
      xAt: () => width / 2,
      yAt: () => height / 2,
    };
  }

  let xMinimum = finite[0].time;
  let xMaximum = finite[0].time;
  let yMinimum = finite[0].value;
  let yMaximum = finite[0].value;
  for (let index = 1; index < finite.length; index += 1) {
    const point = finite[index];
    if (point.time < xMinimum) xMinimum = point.time;
    if (point.time > xMaximum) xMaximum = point.time;
    if (point.value < yMinimum) yMinimum = point.value;
    if (point.value > yMaximum) yMaximum = point.value;
  }

  const xAt = (value) => xMinimum === xMaximum
    ? width / 2
    : ((value - xMinimum) / (xMaximum - xMinimum)) * width;
  const yAt = (value) => yMinimum === yMaximum
    ? height / 2
    : height - ((value - yMinimum) / (yMaximum - yMinimum)) * height;
  const selected = retainMinMax(finite, pointBudget);
  const points = selected.map((point, index) => ({
    ...point,
    move: index === 0 || selected[index - 1].segment !== point.segment,
    x: coordinate(xAt(point.time)),
    y: coordinate(yAt(point.value)),
  }));
  const path = points
    .map((point) => `${point.move ? 'M' : 'L'}${point.x},${point.y}`)
    .join(' ');

  return {
    points,
    path,
    xDomain: [xMinimum, xMaximum],
    yDomain: [yMinimum, yMaximum],
    finiteCount: finite.length,
    xAt,
    yAt,
  };
}

export function createNearestPointLookup(time, values) {
  const points = collectFinitePoints(time, values);
  let nonDecreasing = true;
  for (let index = 1; index < points.length; index += 1) {
    if (points[index].time < points[index - 1].time) {
      nonDecreasing = false;
      break;
    }
  }

  function linear(target) {
    let nearest = points[0];
    let distance = Math.abs(nearest.time - target);
    for (let index = 1; index < points.length; index += 1) {
      const candidate = points[index];
      const candidateDistance = Math.abs(candidate.time - target);
      if (candidateDistance < distance || (candidateDistance === distance && candidate.index < nearest.index)) {
        nearest = candidate;
        distance = candidateDistance;
      }
    }
    return nearest.index;
  }

  function binary(target) {
    const lowerBound = (value) => {
      let start = 0;
      let end = points.length;
      while (start < end) {
        const middle = (start + end) >>> 1;
        if (points[middle].time < value) start = middle + 1;
        else end = middle;
      }
      return start;
    };
    let low = 0;
    let high = points.length;
    while (low < high) {
      const middle = (low + high) >>> 1;
      if (points[middle].time < target) low = middle + 1;
      else high = middle;
    }
    if (low === 0) return points[0].index;
    if (low === points.length) return points[points.length - 1].index;
    const before = points[low - 1];
    const after = points[low];
    const beforeDistance = Math.abs(before.time - target);
    const afterDistance = Math.abs(after.time - target);
    if (beforeDistance <= afterDistance) return points[lowerBound(before.time)].index;
    return after.index;
  }

  return {
    strategy: nonDecreasing ? 'binary' : 'linear',
    find(target) {
      if (!Number.isFinite(target) || points.length === 0) return null;
      return nonDecreasing ? binary(target) : linear(target);
    },
  };
}

/** Nice axis ticks on 1/2/2.5/5 steps covering [minimum, maximum]. */
export function niceTicks(minimum, maximum, targetCount = 5) {
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) return [];
  const target = Number.isFinite(targetCount) && targetCount > 1 ? Math.floor(targetCount) : 5;
  if (minimum === maximum) return [minimum];
  const low = Math.min(minimum, maximum);
  const high = Math.max(minimum, maximum);
  const rawStep = (high - low) / target;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const step = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10) * magnitude;
  const first = Math.floor(low / step + 1e-9) * step;
  const last = Math.ceil(high / step - 1e-9) * step;
  const ticks = [];
  for (let value = first; value <= last + step * 1e-9; value += step) {
    ticks.push(Number(value.toFixed(12)));
  }
  if (ticks.length === 0) return [Number(low.toFixed(12)), Number(high.toFixed(12))];
  return ticks;
}

/** Inclusive brush window; a reversed drag still selects, an empty one selects nothing. */
/* Trend svg geometry: viewBox 640x400, plot gutters 76 left / 24 right.
 * The svg fills its viewport (flex height), so `meet` letterboxes whenever the
 * viewport aspect differs — pointer math must go through the drawn area only. */
export const TREND_VIEW_WIDTH = 640;
export const TREND_VIEW_HEIGHT = 400;
export const TREND_GUTTER_LEFT = 76;
export const TREND_GUTTER_RIGHT = 24;

export function fitViewBoxLetterbox(rectWidth, rectHeight, viewWidth = TREND_VIEW_WIDTH, viewHeight = TREND_VIEW_HEIGHT) {
  const safeRectWidth = Number.isFinite(rectWidth) && rectWidth > 0 ? rectWidth : viewWidth;
  const safeRectHeight = Number.isFinite(rectHeight) && rectHeight > 0 ? rectHeight : viewHeight;
  const scale = Math.min(safeRectWidth / viewWidth, safeRectHeight / viewHeight);
  const drawnWidth = viewWidth * scale;
  const drawnHeight = viewHeight * scale;
  return {
    scale,
    drawnWidth,
    drawnHeight,
    offsetX: (safeRectWidth - drawnWidth) / 2,
    offsetY: (safeRectHeight - drawnHeight) / 2,
  };
}

export function clientToDataX(clientX, rectLeft, rectWidth, rectHeight, xMin, xMax) {
  if (!(xMax > xMin)) return xMin;
  const fit = fitViewBoxLetterbox(rectWidth, rectHeight);
  const plotLeft = rectLeft + fit.offsetX + TREND_GUTTER_LEFT * fit.scale;
  const plotWidth = (TREND_VIEW_WIDTH - TREND_GUTTER_LEFT - TREND_GUTTER_RIGHT) * fit.scale;
  const fraction = (clientX - plotLeft) / plotWidth;
  return xMin + Math.max(0, Math.min(1, fraction)) * (xMax - xMin);
}

export function applyBrushDomain(time, values, start, end) {
  const low = Math.min(start, end);
  const high = Math.max(start, end);
  const keptTime = [];
  const keptValues = [];
  const count = Math.min(time.length, values.length);
  for (let index = 0; index < count; index += 1) {
    if (time[index] >= low && time[index] <= high) {
      keptTime.push(time[index]);
      keptValues.push(values[index]);
    }
  }
  return { time: keptTime, values: keptValues };
}

const PRESSURE_CODES = new Set(['PT', 'P']);

function isPressureVariable(variable) {
  if (typeof variable !== 'string') return false;
  const code = variable.toUpperCase();
  return PRESSURE_CODES.has(code) || code.startsWith('P');
}

/** First pressure variable wins; otherwise the first variable; null when empty. */
export function pickAutoPlotVariable(variables) {
  if (!Array.isArray(variables) || variables.length === 0) return null;
  return variables.find((item) => isPressureVariable(item?.variable)) ?? variables[0] ?? null;
}

// Nice ticks round outward, so the first and last can sit outside the data
// range and be drawn off the plot; keep the ones inside it (the two ends when none fit).
export function ticksWithin(ticks, minimum, maximum) {
  const low = Math.min(minimum, maximum);
  const high = Math.max(minimum, maximum);
  if (low === high) return [low];
  const tolerance = (high - low) * 1e-9;
  const inside = ticks.filter((value) => value >= low - tolerance && value <= high + tolerance);
  return inside.length >= 2 ? inside : [low, high];
}
