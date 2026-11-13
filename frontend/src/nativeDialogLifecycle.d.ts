export interface NativeDialogHandle {
  readonly requestId: string;
  readonly sequence: number;
  readonly contextGeneration?: number;
}

export interface NativeDialogLifecycle {
  mount(): void;
  begin(requestId: string, contextGeneration?: number): NativeDialogHandle;
  markTerminal(handle: NativeDialogHandle, contextGeneration?: number): boolean;
  cancelForContextChange(contextGeneration: number): string | null;
  dispose(): string | null;
  isDisposed(): boolean;
}

export function createNativeDialogLifecycle(
  cancel: (requestId: string, options: { readonly keepalive: true }) => void | Promise<unknown>,
): NativeDialogLifecycle;
