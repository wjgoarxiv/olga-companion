/** W2-L3b (M8): workspace-root scoping for receipt-backed results.
 * Hidden-other applies FIRST at root level (`root ?? 'unknown'` → other);
 * the case-only checkbox then applies WITHIN the visible pool. */

export const UNKNOWN_ROOT = 'unknown';

export type ScopableResult = {
  readonly id: string;
  readonly origin: string;
  readonly source_name?: string | null;
  readonly root?: unknown;
};

/** Equate separator, case, and trailing-slash variants of one root. */
export function normalizeWorkspaceRoot(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (trimmed === '') return null;
  let out = trimmed.replace(/\\/g, '/').replace(/\/{2,}/g, '/');
  if (out.length > 1) out = out.replace(/\/{1,}$/, '');
  if (/^[a-zA-Z]:$/.test(out)) out = `${out}/`;
  return out.toLowerCase();
}

/** Raw scope of one item: its root, or unknown when untagged. */
export function scopeRootOf(result: ScopableResult): string {
  return typeof result.root === 'string' && result.root.trim() !== '' ? result.root : UNKNOWN_ROOT;
}

export function isForeignResult(result: ScopableResult, currentRoot: string | null): boolean {
  if (result.origin !== 'run') return false;
  if (currentRoot === null) return false;
  const current = normalizeWorkspaceRoot(currentRoot);
  if (current === null) return false;
  return normalizeWorkspaceRoot(scopeRootOf(result)) !== current;
}

export function splitByRoot<T extends ScopableResult>(
  results: readonly T[],
  currentRoot: string | null,
  showOther: boolean,
): { readonly visible: T[]; readonly hiddenOther: number } {
  if (showOther || currentRoot === null) return { visible: [...results], hiddenOther: 0 };
  const visible = results.filter((result) => !isForeignResult(result, currentRoot));
  return { visible, hiddenOther: results.length - visible.length };
}
