// R9: a .ppl figure export saves the timestep the user is looking at.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const api = await readFile(new URL('../src/resultApi.ts', import.meta.url), 'utf8');
const exportsState = await readFile(new URL('../src/useResultExports.ts', import.meta.url), 'utf8');

test('profile figure export sends the selected timestep', () => {
  assert.match(api, /exportProfilePlot\([\s\S]*?timestep\?: number/);
  assert.match(api, /\{ path, variables: \[variable\], branch, timestep \}/);
  assert.match(exportsState, /exportProfilePlot\(selected\.id, profile\.variable, branch, timestep \?\? undefined\)/);
});

test('the plot for the timestep comes first', async () => {
  const { profilePlotFirst } = await import('../src/profilePlot.mjs');
  assert.match(api, /return profilePlotFirst\(exported\)/);
  const exported = { ok: true, plots: ['p_t0.png', 'p_t60.png', 'p_t120.png'], selected_plot: 'p_t60.png', documents: [] };
  assert.deepEqual(profilePlotFirst(exported).plots, ['p_t60.png', 'p_t0.png', 'p_t120.png']);
  assert.deepEqual(profilePlotFirst({ ...exported, selected_plot: null }).plots, exported.plots);
});
