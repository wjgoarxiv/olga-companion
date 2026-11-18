// Example cards draw what each example builds: flow left to right, risers up, hills up and down.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { layoutDiagram } from '../src/exampleDiagramLayout.mjs';

const line = (segments, extra = {}) => ({
  nodes: [{ id: 'WELL', kind: 'source' }, { id: 'SEP', kind: 'sink' }],
  edges: [{ id: 'L', from: 'WELL', to: 'SEP', segments, valves: [] }],
  thermal: false, scheduled_valves: false, ...extra,
});

test('a riser ends higher than it starts', () => {
  const v = layoutDiagram(line([{ id: 'SEABED', length_m: 1500, rise_m: -5 }, { id: 'RISER', length_m: 120, rise_m: 120 }]));
  const well = v.nodes.find((n) => n.id === 'WELL');
  const sep = v.nodes.find((n) => n.id === 'SEP');
  assert.ok(sep.y < well.y - 20, `${sep.y} vs ${well.y}`);
  assert.ok(sep.x > well.x);
  const last = v.paths[0].points.at(-1);
  assert.deepEqual([Math.round(last[0]), Math.round(last[1])], [Math.round(sep.x), Math.round(sep.y)]);
});

test('a hilly line goes down and up again', () => {
  const v = layoutDiagram(line([{ id: 'a', length_m: 500, rise_m: -30 }, { id: 'b', length_m: 500, rise_m: 40 }, { id: 'c', length_m: 500, rise_m: -10 }]));
  const ys = v.paths[0].points.map((p) => p[1]);
  assert.ok(ys[1] > ys[0] && ys[2] < ys[1], ys.join(','));
});

test('a merge puts the sources left, the junction in the middle and the sink right', () => {
  const v = layoutDiagram({
    nodes: [{ id: 'A', kind: 'source' }, { id: 'B', kind: 'source' }, { id: 'M', kind: 'junction' }, { id: 'S', kind: 'sink' }],
    edges: [
      { id: '1', from: 'A', to: 'M', segments: [], valves: [] },
      { id: '2', from: 'B', to: 'M', segments: [], valves: [] },
      { id: '3', from: 'M', to: 'S', segments: [], valves: [] },
    ],
    thermal: true, scheduled_valves: false,
  });
  const x = Object.fromEntries(v.nodes.map((n) => [n.id, n.x]));
  assert.ok(x.A === x.B && x.A < x.M && x.M < x.S);
  assert.notEqual(v.ground, null, 'heat loss draws the ground');
  for (const n of v.nodes) assert.ok(n.y > 0 && n.y < v.height);
});

test('a valve sits on its pipe and a scheduled valve is marked', () => {
  const model = line([{ id: 'UP', length_m: 500, rise_m: 0 }, { id: 'DOWN', length_m: 500, rise_m: 0 }]);
  model.edges[0].valves = [{ pipe: 'UP', position: 1, scheduled: true }];
  const valve = layoutDiagram(model).paths[0].valves[0];
  assert.equal(valve.scheduled, true);
  assert.ok(valve.x > 100 && valve.x < 220, String(valve.x));
});

test('the gallery shows the drawing, the badges and the rule in both languages', () => {
  const gallery = readFileSync(new URL('../src/ExampleGallery.tsx', import.meta.url), 'utf8');
  assert.match(gallery, /<ExampleDiagram/);
  assert.match(gallery, /examples\.measured/);
  assert.match(readFileSync(new URL('../src/styles/example-gallery.css', import.meta.url), 'utf8'), /repeat\(auto-fill, minmax\(260px, 1fr\)\)/);
  for (const lang of ['ko', 'en']) {
    const text = readFileSync(new URL(`../src/i18n/${lang}.ts`, import.meta.url), 'utf8');
    for (const key of ['examples.difficultyRule', 'examples.level.advanced', 'examples.components', 'examples.measured']) assert.ok(text.includes(`'${key}'`), `${lang} ${key}`);
  }
});

test('two lines between the same nodes are drawn apart, and labels avoid a rising line', () => {
  const v = layoutDiagram({
    nodes: [{ id: 'IN', kind: 'source' }, { id: 'S', kind: 'junction' }, { id: 'M', kind: 'junction' }, { id: 'OUT', kind: 'sink' }],
    edges: [
      { id: 'f', from: 'IN', to: 'S', segments: [{ id: 'f', length_m: 400, rise_m: 0 }], valves: [] },
      { id: 'n', from: 'S', to: 'M', segments: [{ id: 'u', length_m: 750, rise_m: 15 }, { id: 'd', length_m: 750, rise_m: -15 }], valves: [] },
      { id: 's', from: 'S', to: 'M', segments: [{ id: 's', length_m: 1500, rise_m: 0 }], valves: [] },
      { id: 'o', from: 'M', to: 'OUT', segments: [{ id: 'o', length_m: 500, rise_m: 0 }], valves: [] },
    ],
    thermal: false, scheduled_valves: false,
  });
  const north = v.paths[1].points.map((p) => p[1]);
  const south = v.paths[2].points.map((p) => p[1]);
  assert.ok(Math.min(...north) < Math.min(...south) && Math.max(...south) > Math.max(...north) - 1);
  assert.equal(v.nodes.find((n) => n.id === 'S').labelBelow, true);
  assert.equal(v.nodes.find((n) => n.id === 'OUT').labelBelow, false);
});
