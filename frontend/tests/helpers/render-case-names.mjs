import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { rolldown } from 'rolldown';

const src = (name) => JSON.stringify(fileURLToPath(new URL(`../../src/${name}`, import.meta.url)));
const ENTRY = 'case-names-render-entry';

const entrySource = `
import React, { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ResultReceiptMeta from ${src('ResultReceiptMeta.tsx')};
import TopologyMap from ${src('TopologyMap.tsx')};
import { setLocale } from ${src('i18n/index.ts')};

React.useSyncExternalStore = (_subscribe, getSnapshot) => getSnapshot();

export function renderReceipt(locale, result) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(ResultReceiptMeta, { result }));
}

export function renderTopology(locale, props) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(TopologyMap, props));
}
`;

let rendererPromise;

/** Bundle the real ResultReceiptMeta and TopologyMap once; returns { renderReceipt, renderTopology }. */
export function caseNamesRenderer() {
  rendererPromise ??= (async () => {
    const bundle = await rolldown({
      input: ENTRY,
      platform: 'node',
      plugins: [{
        name: 'case-names-entry',
        resolveId: (id) => (id === ENTRY ? id : null),
        load: (id) => (id === ENTRY ? entrySource : null),
      }],
      resolve: { extensions: ['.tsx', '.ts', '.mjs', '.js'] },
      transform: { define: { 'process.env.NODE_ENV': '"production"' } },
    });
    const { output } = await bundle.generate({ format: 'esm' });
    const dir = await mkdtemp(join(tmpdir(), 'case-names-'));
    const file = join(dir, 'render.mjs');
    await writeFile(file, output[0].code);
    return import(pathToFileURL(file).href);
  })();
  return rendererPromise;
}
