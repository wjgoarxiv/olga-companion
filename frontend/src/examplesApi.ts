import { jsonOrThrow } from './sessionResponse';
import { apiFetch } from './sessionTransport';
import { rememberExampleInstall } from './exampleInstallState.mjs';

export {
  claimExampleInstall,
  exampleErrorKey,
  getExampleInstallBusy,
  loadRememberedExample,
  releaseExampleInstall,
  rememberExampleInstall,
  setExampleWorkspaceRoot,
  subscribeExampleInstallBusy,
} from './exampleInstallState.mjs';

export const EXAMPLES_OPEN_EVENT = 'olga:examples-open';
export const EXAMPLE_INSTALLED_EVENT = 'olga:example-installed';
export const DEMO_EXAMPLE_ID = 'air-water-horizontal';

export interface ExampleCard {
  readonly id: string;
  readonly demo: boolean;
  readonly topology: string;
  readonly fluid: string;
  readonly title_ko: string;
  readonly title_en: string;
  readonly description_ko: string;
  readonly description_en: string;
}

export interface ExampleInstall extends ExampleCard {
  readonly case_rel: string;
  readonly case_name: string;
  readonly table_rel: string;
  readonly next: string;
}

export function requestExamplesOpen(): void {
  window.dispatchEvent(new CustomEvent(EXAMPLES_OPEN_EVENT));
}

export async function fetchExamples(): Promise<readonly ExampleCard[]> {
  const body = (await jsonOrThrow(await apiFetch('/api/examples'))) as { examples?: ExampleCard[] };
  return Array.isArray(body.examples) ? body.examples : [];
}

export async function installExample(id: string): Promise<ExampleInstall> {
  const installed = (await jsonOrThrow(await apiFetch('/api/examples/install', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  }))) as ExampleInstall;
  rememberExampleInstall(installed);
  window.dispatchEvent(new CustomEvent(EXAMPLE_INSTALLED_EVENT, { detail: installed }));
  return installed;
}
