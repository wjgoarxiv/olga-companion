/** A missing reference can be fixed by copying only when it is a relative .tab name inside the case folder. */
export function referenceIsCopyable(reference: string): boolean {
  const normalized = reference.trim().replace(/\\/g, '/');
  if (!normalized || normalized.startsWith('/') || /^[A-Za-z]:/.test(normalized)) return false;
  const parts = normalized.split('/').filter((part) => part !== '' && part !== '.');
  if (parts.length === 0 || parts.includes('..')) return false;
  return parts[parts.length - 1].toLowerCase().endsWith('.tab');
}

/** The plain .tab file name a table can be made under (next to the case), or null when the reference is in a subfolder. */
export function makeableName(reference: string): string | null {
  if (!referenceIsCopyable(reference)) return null;
  const parts = reference.trim().replace(/\\/g, '/').split('/').filter((part) => part !== '' && part !== '.');
  return parts.length === 1 ? parts[0] : null;
}
