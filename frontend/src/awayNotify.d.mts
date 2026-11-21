export declare const AWAY_NOTIFY_KEY: string;
export declare const AWAY_KINDS: readonly string[];
export declare const AWAY_COLLAPSE_WINDOW_MS: number;

export interface AwayNotifyEntry {
  kind: string;
  title: string;
  body?: string;
  count?: number;
  onOpen?: () => void;
}

export declare function browserStorage(): Storage | null;
export declare function readAwayNotifyEnabled(storage: Storage | null | undefined): boolean;
export declare function writeAwayNotifyEnabled(storage: Storage | null | undefined, on: boolean): void;
export declare function loadAwayNotifyEnabled(): boolean;
export declare function saveAwayNotifyEnabled(on: boolean): void;
export declare function shouldNotifyAway(options: {
  hidden: boolean;
  focused: boolean;
  enabled: boolean;
}): boolean;
export declare function createAwayCollapse(options?: {
  now?: () => number;
  windowMs?: number;
}): {
  push(kind: string): { kind: string; count: number; collapsed: boolean };
  clear(): void;
};
export declare function flashTaskbarDefault(): Promise<void>;
export declare function createAwayNotifier(options: {
  showToast: (entry: AwayNotifyEntry) => void;
  flashTaskbar?: (entry: AwayNotifyEntry) => void | Promise<void>;
}): (entry: AwayNotifyEntry) => Promise<void>;

export interface TerminalRun {
  runId: string;
  state: string;
}

export declare function newTerminalRuns(
  timeline: readonly unknown[],
  seenRunIds: Set<string>,
): TerminalRun[];

export declare function shouldSuppressChatDone(options: {
  lastRunNotifiedAt: number | null;
  now?: number;
  windowMs?: number;
}): boolean;
