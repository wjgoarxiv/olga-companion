import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('Icon draws plus, minus, bar and cross as smooth 24x24 stroke vectors', async () => {
  const src = await read('../src/ui/Icon.tsx');
  for (const name of ['plus', 'minus', 'bar', 'cross']) {
    assert.match(src, new RegExp(`\\b${name}:`), `${name} is a vector icon name`);
  }
  assert.match(src, /viewBox="0 0 24 24"/);
  assert.doesNotMatch(src, /<(text|tspan)\b/);
  assert.doesNotMatch(src, /crispEdges/);
});

test('pane frames, step gaps and table heads use aria-hidden decor with no text', async () => {
  const [decor, explorer, centre, dock, panel, step, table, css] = await Promise.all([
    read('../src/ui/PaneDecor.tsx'),
    read('../src/shell/ExplorerPanel.tsx'),
    read('../src/shell/CentreViews.tsx'),
    read('../src/shell/ChatDock.tsx'),
    read('../src/shell/BottomPanel.tsx'),
    read('../src/shell/StepBar.tsx'),
    read('../src/ui/Table.tsx'),
    read('../src/styles/motion.css'),
  ]);
  const nodes = [...decor.matchAll(/<(i|svg)\b[^>]*>/g)].map((match) => match[0]);
  assert.ok(nodes.length >= 4, 'corner marks exist');
  for (const tag of nodes) {
    assert.match(tag, /aria-hidden="true"/, tag);
    assert.doesNotMatch(tag, />[^<]*\p{L}/u, tag);
  }
  assert.doesNotMatch(decor, /·|•|\+/);
  for (const [name, source] of [['explorer', explorer], ['centre', centre], ['dock', dock], ['panel', panel]]) {
    assert.match(source, /<PaneDecor/, `${name} pane carries corner marks`);
    assert.match(source, /pixel-sep/, `${name} pane head has a separator`);
  }
  assert.match(step, /className="pixel-sep step-gap" aria-hidden="true"/);
  assert.match(table, /className="pixel-sep th-sep" aria-hidden="true"/);
  assert.match(css, /\.pane-mark\s*\{[^}]*pointer-events:\s*none/s);
  assert.match(css, /\.pixel-sep\s*\{[^}]*pointer-events:\s*none/s);
  assert.match(css, /@media \(max-width:\s*1100px\)[^]*?\.pane-mark[^}]*display:\s*none/s);
  assert.doesNotMatch(css, /\.pane-mark\s*\{[^}]*animation/s);
  assert.doesNotMatch(css, /\.pixel-sep\s*\{[^}]*animation/s);
  assert.doesNotMatch(`${explorer}\n${centre}\n${dock}\n${panel}\n${step}\n${table}`, /<(button|a)\b[^>]*pixel-sep|pixel-sep[^>]*<(button|a)/);
});
