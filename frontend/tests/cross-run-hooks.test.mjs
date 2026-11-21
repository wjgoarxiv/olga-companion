// N6 review: the overlay hook and the export hook, run for real with a stub session.
// A series from another run is read, re-read and exported from its own file.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const SRC = new URL('../src/', import.meta.url);

async function transpile(name) {
  const source = await readFile(new URL(name, SRC), 'utf8');
  return ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS }, fileName: name }).outputText;
}

function fakeReact() {
  const slots = [];
  let cursor = 0;
  return {
    begin() { cursor = 0; },
    api: {
      useState(initial) {
        const index = cursor++;
        if (!slots[index]) slots[index] = { value: initial };
        const slot = slots[index];
        return [slot.value, (next) => { slot.value = typeof next === 'function' ? next(slot.value) : next; }];
      },
      useRef(initial) {
        const index = cursor++;
        if (!slots[index]) slots[index] = { current: initial };
        return slots[index];
      },
      useEffect() {},
    },
  };
}

function seriesFor(fileId, variable) {
  const unit = fileId === 'D' ? 'psia' : 'bara';
  return {
    variable, position: 'P1', unit, time_unit: 's', time: [0, 1], values: fileId === 'A' ? [1, 2] : [7, 8],
    view: { value_conversion: { dimension: 'pressure', quantity_kind: 'absolute', output_unit: unit }, time_conversion: { output_unit: 's' } },
  };
}

async function load() {
  const calls = [];
  const session = {
    fetchSeries: async (fileId, variable) => {
      calls.push(['fetch', fileId, variable]);
      if (fileId === 'E') throw new Error(`Could not read a series for '${variable}' from case.tpl.`);
      return seriesFor(fileId, variable);
    },
    exportSelectedCsv: async (fileId, variable) => { calls.push(['csv', fileId, variable]); return { download_path: 'x.csv' }; },
    exportPublicationPlot: async (fileId, variable) => { calls.push(['figure', fileId, variable]); return { ok: true, plots: [] }; },
    exportProfileCsv: async (fileId, variable, branch, timestep, bom) => { calls.push(['profile-csv', fileId, variable, branch, timestep, bom]); return { ok: true, csv: 'p.csv' }; },
  };
  const modules = new Map([
    ['./session', session],
    ['./requestEpoch', await import('../src/requestEpoch.mjs')],
    ['./crossRunOverlay.mjs', await import('../src/crossRunOverlay.mjs')],
    ['./trendGeometry', await import('../src/trendGeometry.mjs')],
    ['./unitPreferences', await import('../src/unitPreferences.mjs')],
    ['./sessionFigures', { rememberSessionFigures: () => {} }],
    ['./sessionResponse', { errorCodeOf: (error) => (typeof error?.code === 'string' ? error.code : null) }],
  ]);
  const overlayReact = fakeReact();
  const exportReact = fakeReact();
  const build = async (name, react) => {
    const module = { exports: {} };
    const require = (id) => {
      if (id === 'react') return react.api;
      if (modules.has(id)) return modules.get(id);
      throw new Error(`unexpected import: ${id}`);
    };
    new Function('require', 'module', 'exports', await transpile(name))(require, module, module.exports);
    return module.exports;
  };
  const overlayModule = await build('useResultSeriesOverlay.ts', overlayReact);
  const exportsModule = await build('useResultExports.ts', exportReact);
  const A = { id: 'A', name: 'a.tpl', suffix: '.tpl' };
  const B = { id: 'B', name: 'b.tpl', suffix: '.tpl' };
  const t = (key, vars) => (vars ? `${key} ${JSON.stringify(vars)}` : key);
  const overlay = () => { overlayReact.begin(); return overlayModule.useResultSeriesOverlay(A, t); };
  const exports = () => { exportReact.begin(); return exportsModule.useResultExports({ selected: A, overlay: overlay(), profile: null, branch: null, timestep: null, t }); };
  const P = { id: 'P', name: 'p.ppl', suffix: '.ppl' };
  const profileExports = (profile) => { exportReact.begin(); return exportsModule.useResultExports({ selected: P, overlay: overlay(), profile, branch: 'MAIN', timestep: 3, t }); };
  return { calls, overlay, exports, profileExports, B };
}

const PT = { variable: 'PT', position: 'P1', unit: 'bara' };

test('a series added from another run is exported from that run, not the selected one', async () => {
  const h = await load();
  await h.overlay().toggleVariable(PT);
  await h.overlay().addFromRun(h.B, 'b-run · 09:00');
  const cross = h.overlay().plottedSeries.find((item) => item.fileId === 'B');
  assert.equal(cross.source, 'b-run · 09:00');
  h.overlay().activateSeries(cross.key);
  await h.exports().exportCsv();
  await h.exports().exportPlot();
  assert.deepEqual(h.calls.filter(([kind]) => kind !== 'fetch'), [['csv', 'B', 'PT'], ['figure', 'B', 'PT']]);
  h.overlay().activateSeries(h.overlay().plottedSeries[0].key);
  await h.exports().exportCsv();
  assert.deepEqual(h.calls.at(-1), ['csv', 'A', 'PT']);
});

test('a change of units re-reads each series from its own file', async () => {
  const h = await load();
  await h.overlay().toggleVariable(PT);
  await h.overlay().addFromRun(h.B);
  h.calls.length = 0;
  await h.overlay().changeView({ value_unit: 'barg', range: null });
  assert.deepEqual(h.calls.map(([, fileId]) => fileId).sort(), ['A', 'B']);
});

test('the same run, a second copy and a mismatched unit are refused', async () => {
  const h = await load();
  await h.overlay().toggleVariable(PT);
  await h.overlay().addFromRun({ id: 'A', name: 'a.tpl', suffix: '.tpl' });
  await h.overlay().addFromRun({ id: 'C', name: 'c.ppl', suffix: '.ppl' });
  await h.overlay().addFromRun({ id: 'D', name: 'd.tpl', suffix: '.tpl' });
  assert.match(h.overlay().error, /^overlay\.refuse\.unit /);
  await h.overlay().addFromRun({ id: 'E', name: 'case.tpl', suffix: '.tpl' }, 'valve · 10:30');
  assert.equal(h.overlay().error, 'overlay.refuse.unreadable {"variable":"PT","name":"valve · 10:30"}');
  await h.overlay().addFromRun(h.B);
  await h.overlay().addFromRun(h.B);
  assert.deepEqual(h.overlay().plottedSeries.map((item) => item.fileId), ['A', 'B']);
});

test('the profile CSV passes the For Excel choice through (L3 review)', async () => {
  const h = await load();
  const profile = { variable: 'HOL', branch: 'MAIN', unit: '-', values: [0.1, 0.2] };
  h.profileExports(profile).setCsvExcelBom(true);
  await h.profileExports(profile).exportCsv();
  assert.deepEqual(h.calls.at(-1), ['profile-csv', 'P', 'HOL', 'MAIN', 3, true]);
  h.profileExports(profile).setCsvExcelBom(false);
  await h.profileExports(profile).exportCsv();
  assert.equal(h.calls.at(-1)[5], false);
});
