import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { rolldown } from 'rolldown';

const hookPath = fileURLToPath(new URL('../../src/useApprovalContinuation.ts', import.meta.url));
const ENTRY = '\0approval-hook-entry';

const entrySource = `
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { useApprovalContinuation } from ${JSON.stringify(hookPath)};

// The hook only holds a ref, so one server render is enough to get its callbacks.
export function mountApprovalHook(args) {
  let api;
  function Probe() {
    api = useApprovalContinuation(args);
    return null;
  }
  renderToStaticMarkup(createElement(Probe));
  return api;
}
`;

let mountPromise;

/** Bundle the real useApprovalContinuation once and return mountApprovalHook(args). */
export function approvalHookMounter() {
  mountPromise ??= (async () => {
    const bundle = await rolldown({
      input: ENTRY,
      platform: 'node',
      plugins: [{
        name: 'approval-hook-entry',
        resolveId: (id) => (id === ENTRY ? id : null),
        load: (id) => (id === ENTRY ? entrySource : null),
      }],
      resolve: { extensions: ['.tsx', '.ts', '.mjs', '.js'] },
      transform: { define: { 'process.env.NODE_ENV': '"production"' } },
    });
    const { output } = await bundle.generate({ format: 'esm' });
    const dir = await mkdtemp(join(tmpdir(), 'approval-hook-'));
    const file = join(dir, 'hook.mjs');
    await writeFile(file, output[0].code);
    return (await import(pathToFileURL(file).href)).mountApprovalHook;
  })();
  return mountPromise;
}
