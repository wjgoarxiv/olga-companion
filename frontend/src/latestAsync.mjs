export function createLatestAsyncAction() {
  let epoch = 0;
  return {
    invalidate() {
      epoch += 1;
    },
    async run(operation, handlers) {
      epoch += 1;
      const request = epoch;
      let value;
      try {
        value = await operation();
      } catch (error) {
        if (request === epoch) handlers.onError(error);
        return false;
      }
      if (request !== epoch) return false;
      handlers.onSuccess(value);
      return true;
    },
  };
}
