export function createNativeDialogRequestId(): string;
export function createNativeContextRequestPayload(
  requestId: string,
  contextGeneration: number,
): { readonly request_id: string; readonly context_generation: number };
