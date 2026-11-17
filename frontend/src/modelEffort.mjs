export function normalizeModelEffort(model, effort) {
  const supported = Array.isArray(model?.reasoning_efforts)
    ? model.reasoning_efforts
    : [];
  if (supported.includes(effort)) return effort;
  if (model?.default_effort && supported.includes(model.default_effort)) {
    return model.default_effort;
  }
  if (supported.includes('medium')) return 'medium';
  return supported[0] ?? effort;
}
