import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { rolldown } from 'rolldown';

const cardUrl = process.env.PATROL_CARD_PATH
  ? pathToFileURL(process.env.PATROL_CARD_PATH)
  : new URL('../../src/LifecycleEvidence.tsx', import.meta.url);
const cardPath = fileURLToPath(cardUrl);
const i18nPath = fileURLToPath(new URL('./i18n/index.ts', cardUrl));
const storePath = fileURLToPath(new URL('./runFinishStore.ts', cardUrl));
const ENTRY = '\0patrol-card-render-entry';

const entrySource = `
import React, { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import LifecycleEvidence from ${JSON.stringify(cardPath)};
import { setLocale } from ${JSON.stringify(i18nPath)};
import { clearRunFinishStore, getRunFinish, publishRunFinish } from ${JSON.stringify(storePath)};

// Server rendering reads the default locale snapshot; the card must follow the client store here.
React.useSyncExternalStore = (_subscribe, getSnapshot) => getSnapshot();

export function renderCard(locale, name, result) {
  setLocale(locale);
  return renderToStaticMarkup(createElement(LifecycleEvidence, { name, result }));
}

export { clearRunFinishStore, getRunFinish, publishRunFinish };
`;

let rendererPromise;

/** Bundle the real patrol LifecycleEvidence once and return render helpers.
 *  PATROL_CARD_PATH may point the entry at a copy for broken-copy proofs. */
export function patrolCardRenderer() {
  rendererPromise ??= (async () => {
    const bundle = await rolldown({
      input: ENTRY,
      platform: 'node',
      plugins: [{
        name: 'patrol-card-entry',
        resolveId: (id) => (id === ENTRY ? id : null),
        load: (id) => (id === ENTRY ? entrySource : null),
      }],
      resolve: { extensions: ['.tsx', '.ts', '.mjs', '.js'] },
      transform: { define: { 'process.env.NODE_ENV': '"production"' } },
    });
    const { output } = await bundle.generate({ format: 'esm' });
    const dir = await mkdtemp(join(tmpdir(), 'patrol-card-'));
    const file = join(dir, 'render.mjs');
    await writeFile(file, output[0].code);
    return import(pathToFileURL(file).href);
  })();
  return rendererPromise;
}
