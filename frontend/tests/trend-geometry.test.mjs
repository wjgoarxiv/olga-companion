import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildTrendGeometry,
  createInspectionNavigation,
  createNearestPointLookup,
  finiteSampleOrdinal,
  transitionInspection,
} from '../src/trendGeometry.mjs';

test('100k-sample geometry stays within the pixel budget and preserves extrema and endpoints', () => {
  const count = 100_000;
  const time = Array.from({ length: count }, (_, index) => index * 0.25);
  const values = Array.from({ length: count }, (_, index) => Math.sin(index / 130) * 4 + index / count);
  values[12_345] = -900;
  values[87_654] = 1_200;
  const pointBudget = 360;

  const geometry = buildTrendGeometry(time, values, {
    width: 920,
    height: 380,
    pointBudget,
  });
  const retained = new Set(geometry.points.map((point) => point.index));

  assert.ok(geometry.points.length <= pointBudget * 2 + 4, `rendered ${geometry.points.length} points`);
  assert.ok(retained.has(0), 'first sample is retained');
  assert.ok(retained.has(count - 1), 'last sample is retained');
  assert.ok(retained.has(12_345), 'global minimum is retained');
  assert.ok(retained.has(87_654), 'global maximum is retained');
  assert.deepEqual(geometry.points.map((point) => point.index), geometry.points.map((point) => point.index).toSorted((a, b) => a - b));
  assert.doesNotMatch(geometry.path, /NaN|Infinity/);
});

test('finite gaps become separate SVG move segments without stringifying invalid numbers', () => {
  const geometry = buildTrendGeometry(
    [0, 1, 2, 3, 4, 5],
    [4, 5, Number.NaN, 3, Number.POSITIVE_INFINITY, 6],
    { width: 600, height: 240, pointBudget: 40 },
  );

  assert.equal((geometry.path.match(/M/g) || []).length, 3);
  assert.doesNotMatch(geometry.path, /NaN|Infinity/);
  assert.deepEqual(geometry.points.map((point) => point.index), [0, 1, 3, 5]);
});

test('empty, one-sample, and constant trends produce safe geometry', () => {
  const empty = buildTrendGeometry([], [], { width: 400, height: 200, pointBudget: 20 });
  const one = buildTrendGeometry([9], [7], { width: 400, height: 200, pointBudget: 20 });
  const constant = buildTrendGeometry([0, 1, 2], [7, 7, 7], { width: 400, height: 200, pointBudget: 20 });

  assert.equal(empty.path, '');
  assert.deepEqual(empty.points, []);
  assert.equal(one.points.length, 1);
  assert.equal(constant.points.length, 3);
  for (const path of [one.path, constant.path]) {
    assert.match(path, /^M/);
    assert.doesNotMatch(path, /NaN|Infinity/);
  }
});

test('nearest lookup uses binary search for duplicate non-decreasing time and safe fallback otherwise', () => {
  const duplicate = createNearestPointLookup([0, 1, 1, 4], [10, 11, 12, 13]);
  const nonMonotonic = createNearestPointLookup([0, 4, 1, 3], [10, 14, 11, 13]);
  const withGap = createNearestPointLookup([0, 1, 2], [10, Number.NaN, 12]);

  assert.equal(duplicate.strategy, 'binary');
  assert.equal(duplicate.find(1), 1, 'duplicate ties resolve to the first original sample');
  assert.equal(duplicate.find(3.8), 3);
  assert.equal(nonMonotonic.strategy, 'linear');
  assert.equal(nonMonotonic.find(1.1), 2);
  assert.equal(withGap.find(1.8), 2);
  assert.equal(withGap.find(Number.NaN), null);
});

test('binary midpoint ties resolve to the earliest original sample at the winning duplicate timestamp', () => {
  const lookup = createNearestPointLookup([0, 1, 1, 1, 2], [0, 10, 11, 12, 20]);

  assert.equal(lookup.strategy, 'binary');
  assert.equal(lookup.find(1.5), 1);
  assert.equal(lookup.find(1), 1);
});

test('keyboard inspection transitions use finite sample order for all supported semantic keys', () => {
  const navigation = createInspectionNavigation([0, 1, 2, 3, 4, 5], [10, Number.NaN, 12, 13, Number.POSITIVE_INFINITY, 15]);

  assert.deepEqual(transitionInspection('ArrowRight', null, navigation), { handled: true, nextIndex: 0 });
  assert.deepEqual(transitionInspection('ArrowRight', 0, navigation), { handled: true, nextIndex: 2 });
  assert.deepEqual(transitionInspection('ArrowLeft', null, navigation), { handled: true, nextIndex: 5 });
  assert.deepEqual(transitionInspection('ArrowLeft', 5, navigation), { handled: true, nextIndex: 3 });
  assert.deepEqual(transitionInspection('Home', 3, navigation), { handled: true, nextIndex: 0 });
  assert.deepEqual(transitionInspection('End', 0, navigation), { handled: true, nextIndex: 5 });
  assert.deepEqual(transitionInspection('Escape', 3, navigation), { handled: true, nextIndex: null });
  assert.deepEqual(transitionInspection('PageDown', 3, navigation), { handled: false, nextIndex: 3 });
});

test('gapped inspection reports finite ordinals rather than raw source indices', () => {
  const navigation = createInspectionNavigation([0, 1, 2, 3, 4, 5], [10, Number.NaN, 12, 13, Number.NaN, 15]);

  assert.deepEqual(navigation.indices, [0, 2, 3, 5]);
  assert.equal(finiteSampleOrdinal(0, navigation), 1);
  assert.equal(finiteSampleOrdinal(5, navigation), 4);
  assert.equal(finiteSampleOrdinal(1, navigation), null);
});
