import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { formatUnit } from '../src/formatUnit.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('formatUnit renders display forms with correct casing', () => {
  assert.equal(formatUnit('m3/s'), 'm3/s');
  assert.equal(formatUnit('Pa'), 'Pa');
  assert.equal(formatUnit('C'), '°C');
  assert.equal(formatUnit('bar'), 'bar');
  assert.equal(formatUnit('kg/s'), 'kg/s');
  assert.equal(formatUnit('fraction'), '-');
  assert.equal(formatUnit('dimensionless'), '-');
  assert.equal(formatUnit('kPa'), 'kPa');
  assert.equal(formatUnit('MPa'), 'MPa');
  assert.equal(formatUnit('L/s'), 'L/s');
});

test('formatUnit corrects casing and never reshapes raw codes', () => {
  assert.equal(formatUnit('pa'), 'Pa');
  assert.equal(formatUnit('BAR'), 'bar');
  assert.equal(formatUnit('PT'), 'PT');
  assert.equal(formatUnit('HOL'), 'HOL');
  assert.equal(formatUnit('m'), 'm');
  assert.equal(formatUnit('  Pa  '), 'Pa');
  assert.equal(formatUnit(''), '-');
  assert.equal(formatUnit(null), '-');
});

test('the approval card never routes reviewed inputs through formatUnit', async () => {
  const card = await read('../src/ApprovalCard.tsx');
  assert.doesNotMatch(card, /formatUnit/, 'reviewed inputs render as given');
});
