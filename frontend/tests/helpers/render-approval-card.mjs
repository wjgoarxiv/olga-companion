import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { rolldown } from 'rolldown';

const cardPath = fileURLToPath(new URL('../../src/ApprovalCard.tsx', import.meta.url));
const i18nPath = fileURLToPath(new URL('../../src/i18n/index.ts', import.meta.url));
const ENTRY = '\0approval-card-render-entry';

const entrySource = `
import React, { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ApprovalCard from ${JSON.stringify(cardPath)};
import { setLocale } from ${JSON.stringify(i18nPath)};

// Server rendering reads the default locale snapshot; the card must follow the client store here.
React.useSyncExternalStore = (_subscribe, getSnapshot) => getSnapshot();

export function renderCard(locale, request, props = {}) {
  setLocale(locale);
  const noop = () => undefined;
  return renderToStaticMarkup(createElement(ApprovalCard, {
    request, onApprove: noop, onRecover: noop, onReject: noop,
    pending: false, resolved: false, ...props,
  }));
}
`;

let rendererPromise;

/** Bundle the real ApprovalCard once and return renderCard(locale, request, props). */
export function approvalCardRenderer() {
  rendererPromise ??= (async () => {
    const bundle = await rolldown({
      input: ENTRY,
      platform: 'node',
      plugins: [{
        name: 'approval-card-entry',
        resolveId: (id) => (id === ENTRY ? id : null),
        load: (id) => (id === ENTRY ? entrySource : null),
      }],
      resolve: { extensions: ['.tsx', '.ts', '.mjs', '.js'] },
      transform: { define: { 'process.env.NODE_ENV': '"production"' } },
    });
    const { output } = await bundle.generate({ format: 'esm' });
    const dir = await mkdtemp(join(tmpdir(), 'approval-card-'));
    const file = join(dir, 'render.mjs');
    await writeFile(file, output[0].code);
    return (await import(pathToFileURL(file).href)).renderCard;
  })();
  return rendererPromise;
}
