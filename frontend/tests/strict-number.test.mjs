// N4: every place a person types a number reads it the same strict way; ambiguous text is refused.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { parseStrictNumber } from '../src/strictNumber.mjs';
import { parseCell } from '../src/caseEditModel.mjs';
import { parseFraction } from '../src/tabImport.ts';

const CASES = JSON.parse(readFileSync(new URL('../../tests/fixtures/strict_number_cases.json', import.meta.url), 'utf8'));

test('the shared cases read the same as the Python reader', () => {
  for (const [text, expected] of CASES.accepted) assert.equal(parseStrictNumber(text), expected, text);
  for (const text of CASES.refused) assert.equal(parseStrictNumber(text), null, text);
  for (const text of CASES.comma_off_refused) assert.equal(parseStrictNumber(text, { decimalComma: false }), null, text);
});

function rng(seed) {
  let state = seed >>> 0;
  return () => ((state = (Math.imul(state, 1664525) + 1013904223) >>> 0) / 2 ** 32);
}

test('property: any finite number round-trips through its text', () => {
  const next = rng(20261118);
  for (let i = 0; i < 5000; i += 1) {
    const number = (next() * 2e6 - 1e6) * 10 ** Math.floor(next() * 24 - 12);
    for (const text of [String(number), number.toPrecision(6), number.toExponential(), `  ${number}  `]) {
      assert.equal(parseStrictNumber(text), Number(text), text);
    }
  }
});

test('property: a decimal comma reads as the point unless it looks like a thousands group', () => {
  const next = rng(7);
  for (let i = 0; i < 5000; i += 1) {
    const head = String(Math.floor(next() * 100000));
    const tail = String(Math.floor(next() * 10000)).padStart(1 + Math.floor(next() * 4), '0');
    const grouped = head.length <= 3 && tail.length === 3;
    assert.equal(parseStrictNumber(`${head},${tail}`), grouped ? null : Number(`${head}.${tail}`), `${head},${tail}`);
  }
});

test('the edit table refuses "1,500" instead of reading 1.5, and takes "0,05"', () => {
  assert.equal(parseCell('roughness_m', '1,500').ok, false);
  assert.equal(parseCell('opening', '0x10').ok, false);
  assert.equal(parseCell('opening', '1_0').ok, false);
  const comma = parseCell('opening', '0,5');
  assert.equal(comma.ok, true);
});

test('the water fraction refuses hex and odd text', () => {
  assert.equal(parseFraction('0x0'), null);
  assert.equal(parseFraction('0b1'), null);
  assert.equal(parseFraction('0,25'), 0.25);
  assert.equal(parseFraction('0.25'), 0.25);
});
