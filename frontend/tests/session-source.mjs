import { readFile } from 'node:fs/promises';

export const SESSION_SOURCE_FILES = [
  '../src/session.ts',
  '../src/sessionResponse.ts',
  '../src/sessionTransport.ts',
  '../src/chatSessionApi.ts',
  '../src/workspaceApi.ts',
  '../src/nativeDialogApi.ts',
  '../src/resultContracts.ts',
  '../src/resultApi.ts',
  '../src/runContracts.ts',
  '../src/runApi.ts',
  '../src/sweepApi.ts',
  '../src/lineageNormalization.ts',
];

export async function readSessionSource(baseUrl) {
  const modules = await Promise.all(
    SESSION_SOURCE_FILES.map((path) => readFile(new URL(path, baseUrl), 'utf8')),
  );
  return modules.join('\n');
}
