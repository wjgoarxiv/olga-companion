import type { I18nKey } from './i18n/ko.ts';

export const INSTALL_STORAGE_KEY: string;

export interface ExampleInstallMemory {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export interface RememberedExample {
  readonly id: string;
  readonly caseName: string;
  readonly demo: boolean;
}

export function setExampleWorkspaceRoot(root: string): void;
export function claimExampleInstall(id: string): boolean;
export function releaseExampleInstall(id: string): void;
export function getExampleInstallBusy(): string | null;
export function subscribeExampleInstallBusy(listener: () => void): () => void;
export function exampleErrorKey(message: string): I18nKey;
export function rememberExampleInstall(
  installed: { readonly id: string; readonly case_name: string; readonly demo?: boolean },
  storage?: ExampleInstallMemory | undefined,
  workspaceRoot?: string,
): void;
export function loadRememberedExample(
  storage?: ExampleInstallMemory | undefined,
  workspaceRoot?: string,
): RememberedExample | null;
