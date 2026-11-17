import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('app shell exposes a keyboard bypass and focuses the selected workbench', async () => {
  // Given the application shell source and its layout styles.
  const app = await read('../src/App.tsx');
  const css = await read('../src/styles/shell.css');

  // When the persistent workflow navigation is inspected.
  // Then repeated navigation can be bypassed and the changed surface owns focus.
  assert.match(app, /<a className="skip-link" href="#primary-workbench">\{t\('status\.skipLink'\)\}<\/a>/);
  assert.match(
    app,
    /<main ref=\{workbenchRef\} id="primary-workbench" className="shell-main" tabIndex=\{-1\} aria-label=\{t\('app\.workbench', \{ view \}\)\}>/,
  );
  assert.match(app, /<h1 className="ui-visually-hidden">\{t\('app\.workbench', \{ view \}\)\}<\/h1>/);
  assert.match(app, /requestAnimationFrame\(\(\) => workbenchRef\.current\?\.focus\(\)\)/);
  assert.match(css, /\.skip-link:focus-visible\s*\{/);
  assert.match(css, /\.shell-main:focus-visible\s*\{/);
});
