export function createApprovalMintLifecycle() {
  let epoch = 0;
  let current = null;
  return {
    begin(generation) {
      current?.controller.abort();
      epoch += 1;
      const controller = new AbortController();
      current = { epoch, generation, signal: controller.signal, controller };
      return current;
    },
    invalidate() {
      epoch += 1;
      current?.controller.abort();
      current = null;
    },
    isCurrent(request) {
      return current === request && request.epoch === epoch;
    },
    finish(request) {
      if (current === request) current = null;
    },
  };
}

export async function runApprovalMint(lifecycle, generation, getGeneration, mint, handlers) {
  const request = lifecycle.begin(generation);
  const isCurrent = () => lifecycle.isCurrent(request) && getGeneration() === generation;
  try {
    const value = await mint(request.signal);
    if (!isCurrent()) return false;
    await handlers.onToken(value, request);
    return true;
  } catch (error) {
    if (!isCurrent() || request.signal.aborted) return false;
    handlers.onError(error, request);
    return false;
  } finally {
    if (lifecycle.isCurrent(request)) {
      const generationIsCurrent = getGeneration() === generation;
      lifecycle.finish(request);
      if (generationIsCurrent) handlers.onFinish(request);
    }
  }
}
