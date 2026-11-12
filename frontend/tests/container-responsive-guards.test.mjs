import { readFile } from 'node:fs/promises';
import test from 'node:test';
import assert from 'node:assert/strict';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

const readCss = async () => {
  const root = await read('../src/styles.css');
  const imports = [...root.matchAll(/@import ['"](.+)['"];/g)];
  const imported = await Promise.all(imports.map((match) => read(`../src/${match[1]}`)));
  return [root, ...imported].join('\n');
};

// These panes carry their own inner rails (Results inventory, Workspace file
// list), so their usable width is decided by the container, not the viewport.
// A viewport media query cannot describe them: at a 820px viewport the prompt
// container measured 364px, the 240-320px aside track took its maximum, the
// text column collapsed to 26px and the copy overflowed it by 57px.
test('blank-state prompt reflows against its own container, not the viewport', async () => {
  const css = await readCss();

  assert.match(
    css,
    /\.workbench-prompt\s*\{[^}]*container-type:\s*inline-size/s,
    'the blank-state prompt must establish a size-query container'
  );
  assert.match(
    css,
    /@container \(max-width:\s*580px\)\s*\{[^}]*\.workbench-prompt-hero,\s*\.workbench-prompt-steps\s*\{[^}]*grid-template-columns:\s*1fr/s,
    'a narrow container must stack the hero and the step list instead of starving the text column'
  );
});

// The nav rail is user-resizable and is commonly narrowed well below its 210px
// default, so its contents must respond to the rail rather than the viewport.
// Without min-width:0 the label could not shrink and pushed the "no case"
// badge 36px past the nav item and 23px past the rail itself.
test('activity rail keeps every destination labelled and touch-safe', async () => {
  const [rail, css] = await Promise.all([
    read('../src/shell/ActivityBar.tsx'),
    readCss(),
  ]);

  assert.match(rail, /label=\{labelFor\(entry\.view, t\)\}/, 'every view exposes its destination label');
  assert.ok(rail.includes('(${entry.shortcut})'), 'shortcuts stay discoverable in tooltips');
  assert.match(css, /\.wb-activity \.ui-iconbutton\s*\{[^}]*width:\s*44px[^}]*height:\s*44px/s, 'activity targets stay touch-safe');
  assert.match(css, /\.wb-activity-icon\s*\{[^}]*display:\s*inline-flex/s, 'icons stay centred in their targets');
});
