import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { changeLabel, runColor } from '../src/runIdentity.mjs';
import { runLabel } from '../src/crossRunLabel.mjs';

/* 0.1.22 row 3: a run of an approved edit copy is named by the change the user approved, in the
 * units the edit table shows. A hand-made or older case keeps "<case> · <time>". */

const KO = {
  'caseEdit.field.setpoint': 'PID 설정값 (SETPOINT)',
  'caseEdit.field.gain': 'PID 게인 (AMPLIFICATION)',
  'caseEdit.field.end_time_s': '시뮬레이션 종료 시간',
  'caseEdit.field.max_dt_s': '최대 시간 간격 (MAXDT)',
  'caseEdit.field.min_dt_s': '최소 시간 간격 (MINDT)',
  'runLabel.more': '외 {count}개',
};
const t = (key, vars = {}) => (KO[key] ?? key).replace(/\{(\w+)\}/g, (_, name) => String(vars[name]));

const setpoint = { path: 'controllers.PC.setpoint', before: 2_000_000, after: 2_500_000, unit: 'Pa' };
const run = (changes) => ({ id: 'run:a/case.tpl', name: 'case.tpl', source_name: 'loop_case.edit1.genkey', modified_ns: 1_763_000_000_000_000, ...(changes ? { approved_change: { source_name: 'loop_case.genkey', changes } } : {}) });

test('a pressure setpoint change reads in bar with the loop label', () => {
  assert.equal(changeLabel(run([setpoint]), t), 'PC PID 설정값 20→25 bar');
});

test('a flow setpoint stays in kg/s and a gain has no unit', () => {
  const flow = { path: 'controllers.FC.setpoint', before: 3, after: 4, unit: 'kg/s' };
  const gain = { path: 'controllers.PC.gain', before: 0.5, after: 0.8 };
  assert.equal(changeLabel(run([flow, gain]), t), 'FC PID 설정값 3→4 kg/s, PC PID 게인 0.5→0.8');
});

test('a grouped change is split by field and more than three changes end with a count', () => {
  const step = { path: 'integration.time_step', before: { max_dt_s: 10, min_dt_s: 0.1 }, after: { max_dt_s: 5, min_dt_s: 0.01 } };
  const end = { path: 'integration.end_time_s', before: 600, after: 1200 };
  const label = changeLabel(run([step, end, setpoint]), t);
  assert.match(label, /^최대 시간 간격 10→5 s, 최소 시간 간격 0\.1→0\.01 s, 시뮬레이션 종료 시간 600→1200 s 외 1개$/);
});

test('review R5: a grouped loop change keeps the setpoint unit; unchanged fields are not named', () => {
  const values = { path: 'controllers.PC.values', before: { setpoint: 2_000_000, gain: 0.5, integral_s: 10 }, after: { setpoint: 2_500_000, gain: 0.8, integral_s: 10 }, unit: 'Pa' };
  assert.equal(changeLabel(run([values]), t), 'PC PID 설정값 20→25 bar, PC PID 게인 0.5→0.8');
});

test('review R5: a source change names the source and only the field that changed', () => {
  const KO2 = { ...KO, 'caseEdit.field.mass_flow_kg_s': '질량 유량' };
  const t2 = (key, vars = {}) => (KO2[key] ?? key).replace(/\{(\w+)\}/g, (_, name) => String(vars[name]));
  const source = { path: 'massflow_sources.SRC', before: { mass_flow_kg_s: 3, temperature_c: 20, gas_fraction: 0.5 }, after: { mass_flow_kg_s: 4, temperature_c: 20, gas_fraction: 0.5 } };
  assert.equal(changeLabel(run([source]), t2), 'SRC 질량 유량 3→4 kg/s');
  const geometry = { path: 'pipes.P1.geometry', before: { diameter_m: 0.2, centerline_m: [[0, 0], [100, 0]] }, after: { diameter_m: 0.25, centerline_m: [[0, 0], [100, 0]] } };
  assert.doesNotMatch(changeLabel(run([geometry]), t2), /centerline/);
});

test('a hand-made case or a malformed record has no change label and keeps case · time', () => {
  assert.equal(changeLabel(run(null), t), null);
  assert.equal(changeLabel({ approved_change: { changes: [] } }, t), null);
  assert.equal(changeLabel({ approved_change: { changes: 'x' } }, t), null);
  const plain = runLabel(run(null), 'ko', t);
  assert.match(plain, /^loop_case\.edit1\.genkey · /);
});

test('the run label puts the approved change before case · time', () => {
  const label = runLabel(run([setpoint]), 'ko', t);
  assert.match(label, /^PC PID 설정값 20→25 bar — loop_case\.edit1\.genkey · /);
});

test('the same run gets the same colour token every time', () => {
  assert.equal(runColor('run:a/case.tpl'), runColor('run:a/case.tpl'));
  assert.match(runColor('run:a/case.tpl'), /^var\(--s[1-5]\)$/);
  const spread = new Set(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map((id) => runColor(`run:${id}/case.tpl`)));
  assert.ok(spread.size > 1, 'different runs do not all share one colour');
});

test('PVT D4: the trend and profile files of one run share its colour', () => {
  for (const run of ['a', 'b', 'c', 'd', 'ceb8fe1072a4']) {
    assert.equal(runColor(`run:${run}/case.tpl`), runColor(`run:${run}/case.ppl`), run);
  }
});

test('the results rail and the picker show the change label', async () => {
  const rail = await readFile(new URL('../src/ResultsInventoryRail.tsx', import.meta.url), 'utf8');
  assert.match(rail, /changeLabel\(f, t\)/);
  assert.match(rail, /className="rv-run-chip"[^>]*runColor\(f\.id\)/);
  const picker = await readFile(new URL('../src/CrossRunPicker.tsx', import.meta.url), 'utf8');
  assert.match(picker, /runLabel\(file, locale, t\)/);
});
