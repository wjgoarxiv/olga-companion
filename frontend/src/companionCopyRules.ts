/** A missing reference can be fixed by copying only when it is a relative .tab name inside the case folder. */
export function referenceIsCopyable(reference: string): boolean {
  const normalized = reference.trim().replace(/\\/g, '/');
  if (!normalized || normalized.startsWith('/') || /^[A-Za-z]:/.test(normalized)) return false;
  const parts = normalized.split('/').filter((part) => part !== '' && part !== '.');
  if (parts.length === 0 || parts.includes('..')) return false;
  return parts[parts.length - 1].toLowerCase().endsWith('.tab');
}
