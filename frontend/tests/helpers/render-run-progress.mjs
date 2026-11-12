import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { rolldown } from 'rolldown';

const componentUrl = process.env.RUN_PROGRESS_PATH
  ? pathToFileURL(process.env.RUN_PROGRESS_PATH)
  : new URL('../../src/RunProgress.tsx', import.meta.url);
const componentPath = fileURLToPath(componentUrl);
const i18nPath = fileURLToPath(new URL('./i18n/index.ts', componentUrl));
const ENTRY = '\0run-progress-render-entry';

const entrySource = `
import React, { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { RunProgress } from ${JSON.stringify(componentPath)};
import { setLocale } from ${JSON.stringify(i18nPath)};

// Server rendering reads the default locale snapshot; follow the requested locale here.
React.useSyncExternalStore = (_subscribe, getSnapshot) => getSnapshot();

export function renderProgress(locale, progress) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(RunProgress, { progress }));
}
`;

let rendererPromise;

/** RUN_PROGRESS_PATH may point the entry at a copy for broken-copy proofs. */
export function runProgressRenderer() {
  rendererPromise ??= (async () => {
    const bundle = await rolldown({
      input: ENTRY,
      platform: 'node',
      plugins: [{
        name: 'run-progress-entry',
        resolveId: (id) => (id === ENTRY ? id : null),
        load: (id) => (id === ENTRY ? entrySource : null),
      }],
      resolve: { extensions: ['.tsx', '.ts', '.mjs', '.js'] },
      transform: { define: { 'process.env.NODE_ENV': '"production"' } },
    });
    const { output } = await bundle.generate({ format: 'esm' });
    const dir = await mkdtemp(join(tmpdir(), 'run-progress-'));
    const file = join(dir, 'render.mjs');
    await writeFile(file, output[0].code);
    return import(pathToFileURL(file).href);
  })();
  return rendererPromise;
}
