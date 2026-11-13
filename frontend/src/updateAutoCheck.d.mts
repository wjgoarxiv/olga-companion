import type { Update } from '@tauri-apps/plugin-updater';

export const CHECK_ON_LAUNCH_KEY: string;
export const LAUNCH_CHECK_DELAY_MS: number;

type KeyValueStorage = Pick<Storage, 'getItem' | 'setItem'> | null | undefined;

export function browserStorage(): Storage | null;
export function readCheckOnLaunch(storage: KeyValueStorage): boolean;
export function writeCheckOnLaunch(storage: KeyValueStorage, on: boolean): void;
export function peekFoundUpdate(): Update | null;
export function clearFoundUpdate(): void;
export function subscribeFoundUpdate(listener: () => void): () => void;
export function requestOpenUpdates(): void;
export function subscribeOpenUpdates(listener: () => void): () => void;

export type LaunchCheckOutcome = { readonly kind: 'none' } | { readonly kind: 'available'; readonly version: string };

export function runLaunchCheck(options: {
  readonly enabled: boolean;
  readonly check: () => Promise<Update | null>;
  readonly wait: (ms: number) => Promise<void>;
  readonly delayMs?: number;
  readonly isCancelled?: () => boolean;
  readonly isEnabled?: () => boolean;
}): Promise<LaunchCheckOutcome>;
