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

test('a pipe diameter is shown and typed in mm and kept inside the grammar range (0.1.20 row 3)', async () => {
  const { translate } = await import('../src/i18n/index.ts');
  assert.equal(displayUnit('diameter_m'), 'mm');
  assert.equal(formatDisplay({ field: 'diameter_m', value: 0.2032 }), '203.2');
  assert.deepEqual(parseCell('diameter_m', '250'), { ok: true, value: 0.25 });
  assert.deepEqual(parseCell('diameter_m', '0'), { ok: false, error: 'caseEdit.error.range.diameter_m' });
  assert.deepEqual(parseCell('diameter_m', '10001'), { ok: false, error: 'caseEdit.error.range.diameter_m' });
  const row = { id: 'd', field: 'diameter_m', value: 0.2, op: { op: 'set_pipe_geometry', flowpath: 'MAIN', pipe: 'UP' } };
  assert.deepEqual(buildOperations([row], { d: '250' }).operations, [{ op: 'set_pipe_geometry', flowpath: 'MAIN', pipe: 'UP', diameter_m: 0.25 }]);
  for (const locale of ['en', 'ko']) {
    for (const key of ['caseEdit.field.diameter_m', 'caseEdit.error.range.diameter_m']) assert.notEqual(translate(locale, key), key, `${locale} ${key}`);
  }
});

test('timing rows: a blank MAXDT is no edit, a typed one is, and each field has words (0.1.20 row 4)', async () => {
  const { translate } = await import('../src/i18n/index.ts');
  const unset = { id: 'integration.max_dt_s', field: 'max_dt_s', value: null, note: 'unset', op: { op: 'set_time_step' } };
  const derived = { id: 'integration.trend_interval_s', field: 'trend_interval_s', value: 60, note: 'derived', op: { op: 'set_time_step' } };
  assert.equal(formatDisplay(unset), '');
  assert.equal(displayUnit('max_dt_s'), 's');
  assert.deepEqual(changedRows([unset, derived], { [unset.id]: '', [derived.id]: '60' }), []);
  assert.deepEqual(buildOperations([unset, derived], { [unset.id]: '5', [derived.id]: '60' }).operations, [{ op: 'set_time_step', max_dt_s: 5 }]);
  assert.deepEqual(parseCell('min_dt_s', '0'), { ok: false, error: 'caseEdit.error.range.min_dt_s' });
  const fields = ['max_dt_s', 'min_dt_s', 'dt_start_s', 'trend_interval_s', 'profile_interval_s', 'output_interval_s'];
  for (const locale of ['en', 'ko']) {
    for (const field of fields) {
      for (const key of [`caseEdit.field.${field}`, `caseEdit.error.range.${field}`]) assert.notEqual(translate(locale, key), key, `${locale} ${key}`);
    }
    for (const note of ['derived', 'default', 'unset']) {
      for (const key of [`caseEdit.note.${note}`, `caseEdit.reviewNote.${note}`]) assert.notEqual(translate(locale, key, { value: '5 s' }), key, `${locale} ${key}`);
    }
  }
});

test('heat-transfer rows: wall thickness in mm, ranges refuse zero, every field has words (0.1.20 row 5)', async () => {
  const { translate } = await import('../src/i18n/index.ts');
  const wall = { id: 'thermal.wall_thickness_m', field: 'wall_thickness_m', value: 0.0127, op: { op: 'set_thermal_value' } };
  assert.equal(displayUnit('wall_thickness_m'), 'mm');
  assert.equal(formatDisplay(wall), '12.7');
  assert.deepEqual(buildOperations([wall], { [wall.id]: '20' }).operations, [{ op: 'set_thermal_value', wall_thickness_m: 0.02 }]);
  assert.deepEqual(parseCell('outer_heat_transfer_coefficient_w_m2k', '0'), { ok: false, error: 'caseEdit.error.range.outer_heat_transfer_coefficient_w_m2k' });
  const fields = ['ambient_temperature_c', 'outer_heat_transfer_coefficient_w_m2k', 'wall_thickness_m', 'wall_conductivity_w_mk', 'wall_heat_capacity_j_kgk', 'wall_density_kg_m3'];
  for (const locale of ['en', 'ko']) {
    for (const field of fields) {
      assert.notEqual(displayUnit(field), '', field);
      for (const key of [`caseEdit.field.${field}`, `caseEdit.error.range.${field}`]) assert.notEqual(translate(locale, key), key, `${locale} ${key}`);
    }
  }
});

test('a prefilled cell that only shows a rounded value is not an edit (0.1.20 review)', () => {
  // ENDTIME 1000 s: the derived trend interval 1000/60 has no short decimal form.
  const rows = [
    { id: 'end', field: 'end_time_s', value: 1000, op: { op: 'set_time_step' } },
    { id: 'trend', field: 'trend_interval_s', value: 1000 / 60, op: { op: 'set_time_step' } },
  ];
  const drafts = { end: '2000', trend: formatDisplay(rows[1]) };
  assert.deepEqual(changedRows(rows, drafts).map((row) => row.id), ['end']);
  const built = buildOperations(rows, drafts);
  assert.equal(built.ok, true);
  assert.deepEqual(built.operations, [{ op: 'set_time_step', end_time_s: 2000 }]);
  assert.equal(buildOperations(rows, { end: formatDisplay(rows[0]), trend: formatDisplay(rows[1]) }).error, 'caseEdit.error.nothingChanged');
});
