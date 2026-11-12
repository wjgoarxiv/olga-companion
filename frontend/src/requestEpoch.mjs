export function createRequestEpoch() {
  let epoch = 0;
  return {
    begin() {
      epoch += 1;
      return epoch;
    },
    isCurrent(request) {
      return request === epoch;
    },
    invalidate() {
      epoch += 1;
    },
  };
}

export function createSingleFlight() {
  let sequence = 0;
  let owner = null;
  return {
    begin() {
      if (owner != null) return null;
      sequence += 1;
      owner = sequence;
      return owner;
    },
    end(request) {
      if (request === owner) owner = null;
    },
    reset() {
      owner = null;
    },
  };
}
