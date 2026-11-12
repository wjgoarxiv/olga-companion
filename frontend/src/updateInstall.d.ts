export type InstallOutcome =
  | { readonly kind: 'installed' }
  | { readonly kind: 'blocked'; readonly code: 'run_active' | 'unconfirmed' | 'stop_failed'; readonly message: string }
  | { readonly kind: 'failed'; readonly message: string; readonly backendStopped: boolean };

export function installUpdate(steps: {
  readonly stop: () => Promise<unknown>;
  readonly install: () => Promise<unknown>;
  readonly relaunch: () => Promise<unknown>;
  readonly describe: (error: unknown) => string;
}): Promise<InstallOutcome>;
