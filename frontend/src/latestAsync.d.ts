export interface LatestAsyncHandlers<T> {
  onSuccess(value: T): void;
  onError(error: unknown): void;
}

export interface LatestAsyncAction {
  invalidate(): void;
  run<T>(operation: () => Promise<T>, handlers: LatestAsyncHandlers<T>): Promise<boolean>;
}

export function createLatestAsyncAction(): LatestAsyncAction;
