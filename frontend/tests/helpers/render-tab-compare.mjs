import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { rolldown } from 'rolldown';

const viewPath = fileURLToPath(new URL('../../src/TabCompareView.tsx', import.meta.url));
const i18nPath = fileURLToPath(new URL('../../src/i18n/index.ts', import.meta.url));
const ENTRY = 'tab-compare-render-entry';

const entrySource = `
import React, { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import TabCompareView from ${JSON.stringify(viewPath)};
import { setLocale } from ${JSON.stringify(i18nPath)};

React.useSyncExternalStore = (_subscribe, getSnapshot) => getSnapshot();

export function renderCompare(locale, result) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(TabCompareView, { result }));
}
`;

let rendererPromise;

/** Bundle the real TabCompareView once and return renderCompare(locale, result). */
export function tabCompareRenderer() {
  rendererPromise ??= (async () => {
    const bundle = await rolldown({
      input: ENTRY,
      platform: 'node',
      plugins: [{
        name: 'tab-compare-entry',
        resolveId: (id) => (id === ENTRY ? id : null),
        load: (id) => (id === ENTRY ? entrySource : null),
      }],
      resolve: { extensions: ['.tsx', '.ts', '.mjs', '.js'] },
      transform: { define: { 'process.env.NODE_ENV': '"production"' } },
    });
    const { output } = await bundle.generate({ format: 'esm' });
    const dir = await mkdtemp(join(tmpdir(), 'tab-compare-'));
    const file = join(dir, 'render.mjs');
    await writeFile(file, output[0].code);
    return (await import(pathToFileURL(file).href)).renderCompare;
  })();
  return rendererPromise;
}
