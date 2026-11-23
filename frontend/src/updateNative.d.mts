export type NativeDownloadEvent =
  | { readonly event: 'Started'; readonly data: { readonly contentLength?: number | null } }
  | { readonly event: 'Progress'; readonly data: { readonly chunkLength: number } }
  | { readonly event: 'Finished' };
type Deps = {
  readonly invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown>;
  readonly Channel?: new () => { onmessage: ((event: NativeDownloadEvent) => void) | null };
};
export declare function downloadNative(version: string, onEvent: (event: NativeDownloadEvent) => void, deps?: Deps): Promise<void>;
export declare function installNative(version: string, deps?: Deps): Promise<void>;
export declare function describeNativeError(error: unknown): { readonly stale: boolean; readonly message: string | null };
