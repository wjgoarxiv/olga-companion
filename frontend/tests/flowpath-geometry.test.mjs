import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildFlowpathProjection,
  defaultFlowpathView,
  transitionSectionSelection,
} from '../src/flowpathGeometry.mjs';
import { en } from '../src/i18n/en.ts';
import { ko } from '../src/i18n/ko.ts';

function point(x, y, z) {
  return { x, y, z };
}

function section(sectionIndex, overrides = {}) {
  const start = overrides.start ?? point(sectionIndex, 0, 0);
  const end = overrides.end ?? point(sectionIndex + 1, 0, 0);
  return {
    section_index: sectionIndex,
    pipe_section_index: overrides.pipe_section_index ?? sectionIndex + 1,
    pipe_label: overrides.pipe_label ?? 'PIPE-1',
    length_m: overrides.length_m ?? 1,
    diameter_m: overrides.diameter_m ?? 0.1524,
    chainage_start_m: overrides.chainage_start_m ?? sectionIndex,
    chainage_end_m: overrides.chainage_end_m ?? sectionIndex + 1,
    start,
    end,
    center: overrides.center ?? point(
      (start.x + end.x) / 2,
      (start.y + end.y) / 2,
      (start.z + end.z) / 2,
    ),
  };
}

function options(view, overrides = {}) {
  return {
    view,
    width: 400,
    height: 240,
    padding: 20,
    elevationExaggeration: 1,
    ...overrides,
  };
}

function projectedPoints(projection) {
  return projection.segments.flatMap(({ start, center, end }) => [start, center, end]);
}

function approximately(actual, expected, tolerance = 1e-9) {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} != ${expected}`);
}

test('buildFlowpathProjection maps X-Z and ignores Y when the view is plan', () => {
  // Given
  const sections = [
    section(0, { start: point(0, 0, 0), end: point(10, 5, 0), length_m: 10 }),
    section(1, { start: point(0, 0, 0), end: point(0, 100, 10), length_m: 10 }),
    section(2, { start: point(0, 900, 0), end: point(10, -900, 0), length_m: 10 }),
  ];

  // When
  const projection = buildFlowpathProjection(sections, options('plan'));

  // Then
  assert.equal(projection.segments[0].start.y, projection.segments[0].end.y, 'X is horizontal');
  assert.equal(projection.segments[1].start.x, projection.segments[1].end.x, 'Z is vertical');
  assert.notEqual(projection.segments[1].start.y, projection.segments[1].end.y);
  assert.deepEqual(projection.segments[0].start, projection.segments[2].start);
  assert.deepEqual(projection.segments[0].end, projection.segments[2].end);
});

test('buildFlowpathProjection maps chainage-Y with selectable elevation exaggeration', () => {
  // Given
  const sections = [section(0, {
    chainage_start_m: 0,
    chainage_end_m: 10,
    start: point(-500, 0, 700),
    end: point(900, 2, -300),
    center: point(123, 1, 456),
    length_m: 10,
  })];

  // When
  const natural = buildFlowpathProjection(sections, options('elevation'));
  const exaggerated = buildFlowpathProjection(
    sections,
    options('elevation', { elevationExaggeration: 10 }),
  );

  // Then
  const naturalSegment = natural.segments[0];
  const exaggeratedSegment = exaggerated.segments[0];
  const naturalSlope = Math.abs(
    (naturalSegment.end.y - naturalSegment.start.y) / (naturalSegment.end.x - naturalSegment.start.x),
  );
  const exaggeratedSlope = Math.abs(
    (exaggeratedSegment.end.y - exaggeratedSegment.start.y)
      / (exaggeratedSegment.end.x - exaggeratedSegment.start.x),
  );
  approximately(exaggeratedSlope / naturalSlope, 10);
  assert.equal(naturalSegment.center.x, (naturalSegment.start.x + naturalSegment.end.x) / 2);
});

test('buildFlowpathProjection produces deterministic finite isometric coordinates', () => {
  // Given
  const axes = [
    section(0, { start: point(0, 0, 0), end: point(1, 0, 0) }),
    section(1, { start: point(0, 0, 0), end: point(0, 1, 0) }),
    section(2, { start: point(0, 0, 0), end: point(0, 0, 1) }),
  ];

  // When
  const first = buildFlowpathProjection(axes, options('isometric'));
  const replay = buildFlowpathProjection(axes, options('isometric'));

  // Then
  assert.deepEqual(replay, first);
  assert.equal(new Set(first.segments.map(({ end }) => `${end.x},${end.y}`)).size, 3);
  assert.ok(projectedPoints(first).every(({ x, y }) => Number.isFinite(x) && Number.isFinite(y)));
});

test('buildFlowpathProjection fits all geometry inside the padded viewport and reports its bounds', () => {
  // Given
  const width = 320;
  const height = 180;
  const padding = 16;
  const sections = [
    section(0, { start: point(-4, 2, 1), end: point(8, 7, 9), length_m: 15 }),
    section(1, { start: point(8, 7, 9), end: point(13, -3, -2), length_m: 16 }),
  ];

  // When
  const projection = buildFlowpathProjection(
    sections,
    options('isometric', { width, height, padding }),
  );

  // Then
  const points = projectedPoints(projection);
  const xs = points.map(({ x }) => x);
  const ys = points.map(({ y }) => y);
  assert.equal(projection.viewBox, `0 0 ${width} ${height}`);
  assert.deepEqual(projection.bounds, {
    minX: Math.min(...xs),
    maxX: Math.max(...xs),
    minY: Math.min(...ys),
    maxY: Math.max(...ys),
  });
  assert.ok(projection.bounds.minX >= padding && projection.bounds.maxX <= width - padding);
  assert.ok(projection.bounds.minY >= padding && projection.bounds.maxY <= height - padding);
  assert.ok(
    (projection.bounds.minX === padding && projection.bounds.maxX === width - padding)
      || (projection.bounds.minY === padding && projection.bounds.maxY === height - padding),
  );
});

test('buildFlowpathProjection safely centers a flat-Z plan without invalid coordinates', () => {
  // Given
  const sections = [
    section(0, { start: point(0, -4, 12), end: point(5, 8, 12), length_m: 5 }),
    section(1, { start: point(5, 8, 12), end: point(10, -2, 12), length_m: 5 }),
  ];

  // When
  const projection = buildFlowpathProjection(sections, options('plan', { height: 160 }));

  // Then
  assert.ok(projectedPoints(projection).every(({ x, y }) => Number.isFinite(x) && Number.isFinite(y)));
  assert.equal(projection.bounds.minY, 80);
  assert.equal(projection.bounds.maxY, 80);
  assert.doesNotMatch(JSON.stringify(projection), /NaN|Infinity/);
});

test('buildFlowpathProjection preserves all 33 section indices in source order and exact endpoints', () => {
  // Given
  const sections = Array.from({ length: 33 }, (_, index) => section(index, {
    pipe_label: `PIPE-${Math.floor(index / 11) + 1}`,
    pipe_section_index: (index % 11) + 1,
  }));

  // When
  const projection = buildFlowpathProjection(sections, options('elevation'));

  // Then
  assert.deepEqual(projection.segments.map(({ section_index }) => section_index), Array.from({ length: 33 }, (_, index) => index));
  assert.deepEqual(projection.segments.map(({ pipe_section_index }) => pipe_section_index), Array.from({ length: 33 }, (_, index) => (index % 11) + 1));
  assert.equal(projection.segments[0].start.x, 20);
  assert.equal(projection.segments[32].end.x, 380);
  for (let index = 1; index < projection.segments.length; index += 1) {
    assert.deepEqual(projection.segments[index - 1].end, projection.segments[index].start);
  }
});

test('buildFlowpathProjection uses demo-shaped section endpoints across horizontal and vertical legs', () => {
  // Given
  const sections = [
    section(0, { chainage_start_m: 0, chainage_end_m: 12, start: point(0, 0, 0), end: point(12, 0, 0), length_m: 12 }),
    section(1, { chainage_start_m: 12, chainage_end_m: 18, start: point(12, 0, 0), end: point(12, 6, 0), length_m: 6 }),
    section(2, { chainage_start_m: 18, chainage_end_m: 27, start: point(12, 6, 0), end: point(21, 6, 0), length_m: 9 }),
  ];

  // When
  const projection = buildFlowpathProjection(sections, options('elevation'));

  // Then
  assert.deepEqual(projection.segments[0].end, projection.segments[1].start);
  assert.deepEqual(projection.segments[1].end, projection.segments[2].start);
  assert.equal(projection.segments[0].start.y, projection.segments[0].end.y);
  assert.notEqual(projection.segments[1].start.y, projection.segments[1].end.y);
  assert.equal(projection.segments[2].start.y, projection.segments[2].end.y);
});

test('transitionSectionSelection provides clamped roving keyboard selection', () => {
  // Given
  const sectionCount = 33;
  const transitions = [
    ['ArrowRight', null, { handled: true, nextIndex: 0 }],
    ['ArrowRight', 0, { handled: true, nextIndex: 1 }],
    ['ArrowRight', 32, { handled: true, nextIndex: 32 }],
    ['ArrowLeft', null, { handled: true, nextIndex: 32 }],
    ['ArrowLeft', 32, { handled: true, nextIndex: 31 }],
    ['Home', 17, { handled: true, nextIndex: 0 }],
    ['End', 17, { handled: true, nextIndex: 32 }],
    ['Escape', 17, { handled: true, nextIndex: null }],
    ['PageDown', 17, { handled: false, nextIndex: 17 }],
  ];

  // When
  const results = transitions.map(([key, currentIndex]) => (
    transitionSectionSelection(key, currentIndex, sectionCount)
  ));

  // Then
  assert.deepEqual(results, transitions.map(([, , expected]) => expected));
  assert.deepEqual(transitionSectionSelection('ArrowRight', null, 0), { handled: true, nextIndex: null });
});

test('projection rejects malformed numeric inputs, infeasible padding, and oversized geometry', () => {
  const valid = [section(0)];
  assert.throws(
    () => buildFlowpathProjection(valid, options('plan', { width: '400' })),
    /width must be finite/,
  );
  assert.throws(
    () => buildFlowpathProjection(valid, options('plan', { padding: 120 })),
    /padding must leave a drawable viewport/,
  );
  assert.throws(
    () => buildFlowpathProjection(Array.from({ length: 5_001 }, (_, index) => section(index)), options('plan')),
    /section limit/,
  );
});

test('selection normalizes invalid counts and clamps out-of-range current indices', () => {
  assert.deepEqual(transitionSectionSelection('ArrowLeft', 99, 33), { handled: true, nextIndex: 31 });
  assert.deepEqual(transitionSectionSelection('ArrowRight', -12, 33), { handled: true, nextIndex: 1 });
  assert.deepEqual(transitionSectionSelection('End', 4, Number.POSITIVE_INFINITY), { handled: true, nextIndex: null });
  assert.deepEqual(transitionSectionSelection('ArrowRight', 4, 2.5), { handled: true, nextIndex: null });
});

const riser = () => [
  section(0, { chainage_start_m: 0, chainage_end_m: 10, start: point(5, 0, 3), end: point(5, 10, 3), length_m: 10 }),
];

test('side view draws a straight-up riser vertical: no horizontal travel, full height', () => {
  const projection = buildFlowpathProjection(riser(), options('side'));
  const { start, end } = projection.segments[0];
  approximately(start.x, end.x);
  assert.ok(start.y - end.y > 100, 'the riser spans the drawable height');
});

test('the chainage elevation view still draws that same riser as a diagonal, which is why it is labelled', () => {
  const { start, end } = buildFlowpathProjection(riser(), options('elevation')).segments[0];
  assert.ok(Math.abs(end.x - start.x) > 50, 'chainage runs along x, so a riser leans');
});

test('side view plots cumulative horizontal distance, so a flat leg then a riser then a flat leg keeps true angles', () => {
  const sections = [
    section(0, { start: point(0, 0, 0), end: point(12, 0, 0), length_m: 12 }),
    section(1, { start: point(12, 0, 0), end: point(12, 6, 0), length_m: 6 }),
    section(2, { start: point(12, 6, 0), end: point(12, 6, 9), length_m: 9 }),
  ];
  const projection = buildFlowpathProjection(sections, options('side'));
  const [flat, up, along] = projection.segments;
  approximately(up.start.x, up.end.x);
  assert.deepEqual(flat.end, up.start);
  assert.deepEqual(up.end, along.start);
  assert.ok(along.end.x > along.start.x, 'travel along z counts as horizontal distance');
  approximately(along.start.y, along.end.y);
  const scale = (flat.end.x - flat.start.x) / 12;
  approximately((along.end.x - along.start.x) / scale, 9, 1e-6);
});

test('side view honours the elevation exaggeration and rejects an unknown view', () => {
  const slope = (exaggeration) => {
    const { start, end } = buildFlowpathProjection(
      [section(0, { start: point(0, 0, 0), end: point(10, 5, 0), length_m: 11 })],
      options('side', { elevationExaggeration: exaggeration }),
    ).segments[0];
    return Math.abs((end.y - start.y) / (end.x - start.x));
  };
  approximately(slope(2) / slope(1), 2);
  assert.throws(() => buildFlowpathProjection(riser(), options('front')), TypeError);
});

test('defaultFlowpathView opens a mostly vertical flowpath in side view and the rest in elevation', () => {
  assert.equal(defaultFlowpathView(riser()), 'side');
  const flat = [section(0, { start: point(0, 0, 0), end: point(20, 2, 0), length_m: 20 })];
  assert.equal(defaultFlowpathView(flat), 'elevation');
  assert.equal(defaultFlowpathView([]), 'elevation');
});

test('captions say in plain words what each axis is, in Korean and English', () => {
  assert.doesNotMatch(ko['flowpath.viewElevationCaption'], /chainage/i);
  assert.match(ko['flowpath.viewElevationCaption'], /가로.*관을 따라 잰 거리.*세로.*높이/);
  assert.match(ko['flowpath.viewElevationCaption'], /\{exaggeration\}배/);
  assert.match(ko['flowpath.viewSideCaption'], /가로.*수평 거리.*세로.*높이/);
  assert.doesNotMatch(en['flowpath.viewElevationCaption'], /chainage/i);
  assert.match(en['flowpath.viewElevationCaption'], /distance along the pipe.*height/i);
  assert.match(en['flowpath.viewElevationCaption'], /\{exaggeration\}×/);
  assert.match(en['flowpath.viewSideCaption'], /horizontal distance.*height/i);
  assert.equal(ko['flowpath.view.side'], '측면');
  assert.equal(en['flowpath.view.side'], 'Side');
});

test('the viewer offers the side view and opens each flowpath in its default view', async () => {
  const { readFile } = await import('node:fs/promises');
  const viewer = await readFile(new URL('../src/FlowpathGeometryViewer.tsx', import.meta.url), 'utf8');
  assert.match(viewer, /\['plan', 'elevation', 'side', 'isometric'\]/);
  assert.match(viewer, /defaultFlowpathView\(sections\)/);
  assert.match(viewer, /flowpath\.viewSideCaption/);
});
