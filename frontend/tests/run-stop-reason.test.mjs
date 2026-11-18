// A failed run is described from the parsed OLGA stop message, never from a guess.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stopReasonView, stopReasonPrompt } from '../src/runStopReason.mjs';

const below = {
  code: 'pressure_below_table', stopped_at_s: 985.6116154, pressure_bara: 0.48789, temperature_c: 24.734,
  where: 'FLOWPATH=MAIN, PIPE=DOWNSTREAM, SECTION=9', exit_code: 65, exit_message: 'pressure below',
  last_lines: ['THE OLGA SIMULATION ABORTED AT TIME 985.61161540 SECONDS.', 'PRESSURE BELOW TABLE VALUES (P = 0.48789 bara, T = 24.734 C)'],
};

test('a table-range stop names the value, the place and the time', () => {
  const view = stopReasonView(below);
  assert.equal(view.titleKey, 'run.stop.title.pressure_below_table');
  assert.equal(view.detailKey, 'run.stop.detail.table');
  assert.deepEqual(view.params, { time: '985.6', where: 'FLOWPATH=MAIN, PIPE=DOWNSTREAM, SECTION=9', p: '0.48789', t: '24.734' });
  assert.deepEqual(view.stepKeys, ['run.stop.step.widerTablePressure', 'run.stop.step.checkBoundary', 'run.stop.step.ask']);
  assert.equal(view.known, true);
});

test('an unknown stop says so and keeps OLGA\'s last lines', () => {
  const view = stopReasonView({ code: 'unknown', stopped_at_s: null, exit_code: 77, exit_message: 'something new', last_lines: ['a', 'b'] });
  assert.equal(view.titleKey, 'run.stop.title.unknown');
  assert.equal(view.detailKey, 'run.stop.detail.unknown');
  assert.equal(view.known, false);
  assert.deepEqual(view.lastLines, ['a', 'b']);
});

test('no reason gives no view', () => {
  assert.equal(stopReasonView(null), null);
  assert.equal(stopReasonView(undefined), null);
});

test('the assistant gets the parsed facts and no file paths', () => {
  const prompt = stopReasonPrompt(below, 'f4_mid_run.genkey');
  assert.match(prompt, /pressure_below_table/);
  assert.match(prompt, /985\.6/);
  assert.match(prompt, /0\.48789 bara/);
  assert.match(prompt, /SECTION=9/);
  assert.match(prompt, /f4_mid_run\.genkey/);
  assert.doesNotMatch(prompt, /[A-Za-z]:\\|\/Users\//);
});

test('the troubleshoot message names the case from the same source the receipt shows', () => {
  const panel = readFileSync(new URL('../src/RunFailurePanel.tsx', import.meta.url), 'utf8');
  assert.match(panel, /stopReasonPrompt\(status\.stop_reason, basename\(status\.source_name \|\| status\.detection\?\.case_source \|\| ''\)\)/);
});
