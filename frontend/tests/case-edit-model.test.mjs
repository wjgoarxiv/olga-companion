// The hand-edit table shows values in engineer units and sends only the changed cells.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildOperations, changedRows, conflictKey, displayUnit, formatDisplay, parseCell, planReasons,
} from '../src/caseEditModel.mjs';

const rows = [
  { id: 'integration.end_time_s', target: 'ENDTIME', field: 'end_time_s', value: 3600, unit: 's', op: { op: 'set_integration' } },
  { id: 'nodes.OUTLET.pressure_pa', target: 'OUTLET', field: 'pressure_pa', value: 200000, unit: 'Pa', op: { op: 'set_boundary_pressure', node: 'OUTLET' } },
  { id: 'equipment.ESD.opening', target: 'ESD', field: 'opening', value: 1, unit: 'fraction', op: { op: 'set_valve_opening', label: 'ESD' }, note: 'schedule' },
  { id: 'flowpaths.MAIN.pipes.UP.roughness_m', target: 'MAIN/UP', field: 'roughness_m', value: 5e-5, unit: 'm', op: { op: 'set_pipe_roughness', flowpath: 'MAIN', pipe: 'UP' } },
];

test('values show in engineer units', () => {
  assert.equal(formatDisplay(rows[1]), '2');
  assert.equal(displayUnit('pressure_pa'), 'bar');
  assert.equal(formatDisplay(rows[2]), '100');
  assert.equal(displayUnit('opening'), '%');
  assert.equal(formatDisplay(rows[3]), '0.05');
  assert.equal(displayUnit('roughness_m'), 'mm');
});

test('a cell typed in bar becomes pascal, a comma decimal is accepted', () => {
  assert.deepEqual(parseCell('pressure_pa', '5'), { ok: true, value: 500000 });
  assert.deepEqual(parseCell('pressure_pa', '4,5'), { ok: true, value: 450000 });
  assert.deepEqual(parseCell('opening', '40'), { ok: true, value: 0.4 });
  assert.deepEqual(parseCell('roughness_m', '0.1'), { ok: true, value: 0.0001 });
});

test('text, blanks and an opening outside 0-100 % are refused before any request', () => {
  assert.equal(parseCell('pressure_pa', 'abc').ok, false);
  assert.equal(parseCell('pressure_pa', '').ok, false);
  assert.equal(parseCell('pressure_pa', '1e400').ok, false);
  assert.equal(parseCell('opening', '120').error, 'caseEdit.error.openingRange');
});

test('unchanged and blank cells produce no operation', () => {
  assert.deepEqual(changedRows(rows, { 'nodes.OUTLET.pressure_pa': '2', 'integration.end_time_s': '' }), []);
  const result = buildOperations(rows, { 'nodes.OUTLET.pressure_pa': '2' });
  assert.deepEqual(result, { ok: false, rowId: null, error: 'caseEdit.error.nothingChanged' });
});

test('changed cells become closed-grammar operations', () => {
  const result = buildOperations(rows, { 'nodes.OUTLET.pressure_pa': '5', 'integration.end_time_s': '7200' });
  assert.equal(result.ok, true);
  assert.deepEqual(result.operations, [
    { op: 'set_integration', end_time_s: 7200 },
    { op: 'set_boundary_pressure', node: 'OUTLET', pressure_pa: 500000 },
  ]);
});

test('a bad cell names its row', () => {
  const result = buildOperations(rows, { 'equipment.ESD.opening': '150' });
  assert.deepEqual(result, { ok: false, rowId: 'equipment.ESD.opening', error: 'caseEdit.error.openingRange' });
});

test('conflicts map to sentences, other codes do not', () => {
  assert.equal(conflictKey('stale_source'), 'caseEdit.conflict.source');
  assert.equal(conflictKey('stale_context'), 'caseEdit.conflict.context');
  assert.equal(conflictKey('refused'), null);
});

test('a refused plan gives its reasons', () => {
  const plan = { publishable: false, errors: [{ code: 'compile_validation_failed', message: 'did not validate', evidence: '' }], validation: { diagnostics: ['E001 bad'] } };
  assert.deepEqual(planReasons(plan), ['did not validate', 'E001 bad']);
  assert.deepEqual(planReasons(undefined), []);
});

test('a value outside what the case accepts is refused in the cell with its own reason', () => {
  assert.deepEqual(parseCell('pressure_pa', '-1'), { ok: false, error: 'caseEdit.error.range.pressure_pa' });
  assert.deepEqual(parseCell('pressure_pa', '0'), { ok: false, error: 'caseEdit.error.range.pressure_pa' });
  assert.deepEqual(parseCell('end_time_s', '0'), { ok: false, error: 'caseEdit.error.range.end_time_s' });
  assert.deepEqual(parseCell('temperature_c', '-300'), { ok: false, error: 'caseEdit.error.range.temperature_c' });
  assert.deepEqual(parseCell('mass_flow_kg_s', '-0.1'), { ok: false, error: 'caseEdit.error.range.mass_flow_kg_s' });
  assert.deepEqual(parseCell('roughness_m', '101'), { ok: false, error: 'caseEdit.error.range.roughness_m' });
  assert.deepEqual(parseCell('opening', '120'), { ok: false, error: 'caseEdit.error.openingRange' });
  assert.equal(parseCell('pressure_pa', '5').ok, true);
  assert.equal(parseCell('mass_flow_kg_s', '0').ok, true);
});
