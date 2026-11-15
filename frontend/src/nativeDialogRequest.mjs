export function createNativeDialogRequestId() {
  const cryptoApi = globalThis.crypto;
  if (!cryptoApi?.randomUUID) {
    throw new Error('Secure request ID generation is unavailable.');
  }
  return `dialog_${cryptoApi.randomUUID().replaceAll('-', '')}`;
}

export function createNativeContextRequestPayload(requestId, contextGeneration) {
  if (!Number.isInteger(contextGeneration) || contextGeneration < 0) {
    throw new RangeError('Context generation must be a nonnegative integer.');
  }
  return { request_id: requestId, context_generation: contextGeneration };
}
