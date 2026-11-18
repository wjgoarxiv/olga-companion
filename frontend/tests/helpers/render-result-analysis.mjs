import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { rolldown } from 'rolldown';

const src = (p) => fileURLToPath(new URL(`../../src/${p}`, import.meta.url));
const ENTRY = '\0result-analysis-render-entry';

const entrySource = `
import React, { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ResultAnalysis from ${JSON.stringify(src('ResultAnalysis.tsx'))};
import { exportSelectedCsv, exportProfileCsv } from ${JSON.stringify(src('resultApi.ts'))};
import { setLocale } from ${JSON.stringify(src('i18n/index.ts'))};

React.useSyncExternalStore = (_subscribe, getSnapshot) => getSnapshot();

export function renderAnalysis(locale, props) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(ResultAnalysis, {
    selected: { id: 'run:abc/case.tpl', suffix: '.tpl' },
    series: null,
    loading: false,
    publication: null,
    csvExport: null,
    figureExportLoading: false,
    csvExportLoading: false,
    figureExportError: '',
    csvExportError: '',
    exportPlot: () => {},
    exportCsv: () => {},
    ...props,
  }));
}

export { exportSelectedCsv, exportProfileCsv };
`;

let rendererPromise;

export function resultAnalysisRenderer() {
  rendererPromise ??= (async () => {
    const bundle = await rolldown({
      input: ENTRY,
      platform: 'node',
      plugins: [{
        name: 'result-analysis-entry',
        resolveId: (id) => (id === ENTRY ? id : null),
        load: (id) => (id === ENTRY ? entrySource : null),
      }],
      resolve: { extensions: ['.tsx', '.ts', '.mjs', '.js'] },
      transform: { define: { 'process.env.NODE_ENV': '"production"' } },
    });
    const { output } = await bundle.generate({ format: 'esm' });
    const dir = await mkdtemp(join(tmpdir(), 'result-analysis-'));
    const file = join(dir, 'render.mjs');
    await writeFile(file, output[0].code);
    return import(pathToFileURL(file).href);
  })();
  return rendererPromise;
}
