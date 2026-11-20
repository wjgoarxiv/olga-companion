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

test('empty Workspace and Results use a desktop command-board layout', async () => {
  const css = await readCss();
  assert.match(
    css,
    /\.workbench-prompt-hero\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\) minmax\(240px,\s*320px\)/s,
    'desktop prompts should pair orientation copy with a bounded live-context panel'
  );
  assert.match(
    css,
    /\.workbench-prompt-steps\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/s,
    'desktop next steps should read as two balanced operation cards'
  );
  assert.match(
    css,
    /\.workbench-prompt-footer\s*\{[^}]*display:\s*flex[^}]*align-items:\s*center/s,
    'desktop actions should stay grouped with their operational note'
  );
  assert.match(
    css,
    /@media \(max-width: 760px\)[\s\S]*?\.workbench-prompt-hero,[\s\S]*?\.workbench-prompt-steps\s*\{[^}]*grid-template-columns:\s*1fr/s,
    'mobile empty workbenches must collapse to one column'
  );
});
