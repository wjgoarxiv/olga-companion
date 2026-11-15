const VIEWS = new Set(['plan', 'elevation', 'side', 'isometric']);

function finite(value, label) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new TypeError(`${label} must be finite`);
  }
  return value;
}

function coordinate(point, axis) {
  return finite(point?.[axis] ?? point?.[`${axis}_m`], `point.${axis}`);
}

/* Horizontal run from a section's start to the named point, along x and z. */
function horizontalRun(section, pointName) {
  const from = section.start;
  const to = section[pointName];
  return Math.hypot(coordinate(to, 'x') - coordinate(from, 'x'), coordinate(to, 'z') - coordinate(from, 'z'));
}

function rawPoint(section, pointName, view, exaggeration, sideStart) {
  const point = section[pointName];
  const x = coordinate(point, 'x');
  const y = coordinate(point, 'y');
  const z = coordinate(point, 'z');

  if (view === 'plan') return { x, y: z };
  if (view === 'side') return { x: sideStart + horizontalRun(section, pointName), y: y * exaggeration };
  if (view === 'elevation') {
    const chainage = pointName === 'start'
      ? section.chainage_start_m
      : pointName === 'end'
        ? section.chainage_end_m
        : (finite(section.chainage_start_m, 'chainage_start_m')
          + finite(section.chainage_end_m, 'chainage_end_m')) / 2;
    return { x: finite(chainage, 'chainage'), y: y * exaggeration };
  }
  return { x: x - z, y: ((x + z) * 0.5) - y };
}

function fittedTransform(points, width, height, padding) {
  if (points.length === 0) {
    return {
      map: () => ({ x: width / 2, y: height / 2 }),
      bounds: { minX: width / 2, maxX: width / 2, minY: height / 2, maxY: height / 2 },
    };
  }
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const source = {
    minX: Math.min(...xs), maxX: Math.max(...xs),
    minY: Math.min(...ys), maxY: Math.max(...ys),
  };
  const rangeX = source.maxX - source.minX;
  const rangeY = source.maxY - source.minY;
  const availableWidth = Math.max(0, width - (padding * 2));
  const availableHeight = Math.max(0, height - (padding * 2));
  const scaleX = rangeX > 0 ? availableWidth / rangeX : Number.POSITIVE_INFINITY;
  const scaleY = rangeY > 0 ? availableHeight / rangeY : Number.POSITIVE_INFINITY;
  const scale = Number.isFinite(Math.min(scaleX, scaleY)) ? Math.min(scaleX, scaleY) : 1;
  const drawnWidth = rangeX * scale;
  const drawnHeight = rangeY * scale;
  const offsetX = (width - drawnWidth) / 2;
  const offsetY = (height - drawnHeight) / 2;
  const map = (point) => ({
    x: offsetX + ((point.x - source.minX) * scale),
    y: height - (offsetY + ((point.y - source.minY) * scale)),
  });
  const mapped = points.map(map);
  return {
    map,
    bounds: {
      minX: Math.min(...mapped.map((point) => point.x)),
      maxX: Math.max(...mapped.map((point) => point.x)),
      minY: Math.min(...mapped.map((point) => point.y)),
      maxY: Math.max(...mapped.map((point) => point.y)),
    },
  };
}

export function buildFlowpathProjection(sections, options) {
  if (!Array.isArray(sections)) throw new TypeError('sections must be an array');
  if (sections.length > 5_000) throw new RangeError('flowpath section limit is 5000');
  const view = options?.view;
  if (!VIEWS.has(view)) throw new TypeError('view must be plan, elevation, side, or isometric');
  const width = finite(options?.width, 'width');
  const height = finite(options?.height, 'height');
  const padding = finite(options?.padding, 'padding');
  const elevationExaggeration = finite(options?.elevationExaggeration ?? 1, 'elevationExaggeration');
  if (width <= 0 || height <= 0 || padding < 0 || elevationExaggeration <= 0) {
    throw new RangeError('projection dimensions and exaggeration must be positive');
  }
  if ((padding * 2) >= width || (padding * 2) >= height) {
    throw new RangeError('padding must leave a drawable viewport');
  }

  /* Side view: x is the horizontal distance walked so far, so a vertical pipe adds none. */
  let sideStart = 0;
  const rawSegments = sections.map((section) => {
    const segment = {
      ...section,
      start: rawPoint(section, 'start', view, elevationExaggeration, sideStart),
      center: rawPoint(section, 'center', view, elevationExaggeration, sideStart),
      end: rawPoint(section, 'end', view, elevationExaggeration, sideStart),
    };
    if (view === 'side') sideStart = segment.end.x;
    return segment;
  });
  const points = rawSegments.flatMap(({ start, center, end }) => [start, center, end]);
  const { map, bounds } = fittedTransform(points, width, height, padding);
  return {
    view,
    viewBox: `0 0 ${width} ${height}`,
    bounds,
    segments: rawSegments.map((segment) => ({
      ...segment,
      start: map(segment.start),
      center: map(segment.center),
      end: map(segment.end),
    })),
  };
}

/* A flowpath that climbs more than it runs reads best from the side, where vertical is vertical. */
export function defaultFlowpathView(sections) {
  if (!Array.isArray(sections) || sections.length === 0) return 'elevation';
  let run = 0;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const section of sections) {
    run += horizontalRun(section, 'end');
    for (const name of ['start', 'end']) {
      const y = coordinate(section[name], 'y');
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
    }
  }
  return (maxY - minY) > run ? 'side' : 'elevation';
}

export function transitionSectionSelection(key, currentIndex, sectionCount) {
  const count = Number.isSafeInteger(sectionCount) && sectionCount >= 0 ? sectionCount : 0;
  const current = Number.isSafeInteger(currentIndex) && count
    ? Math.min(Math.max(currentIndex, 0), count - 1)
    : null;
  if (key === 'Escape') return { handled: true, nextIndex: null };
  if (key === 'Home') return { handled: true, nextIndex: count ? 0 : null };
  if (key === 'End') return { handled: true, nextIndex: count ? count - 1 : null };
  if (key === 'ArrowRight' || key === 'ArrowDown') {
    return { handled: true, nextIndex: count ? Math.min((current ?? -1) + 1, count - 1) : null };
  }
  if (key === 'ArrowLeft' || key === 'ArrowUp') {
    return { handled: true, nextIndex: count ? Math.max((current ?? count) - 1, 0) : null };
  }
  return { handled: false, nextIndex: current };
}
