export const FALLBACK_WORKSPACE_LABEL = 'Bundled workspace';

function isFallbackWorkspaceRoot(root: string): boolean {
  const normalizedRoot = root.trim();
  return normalizedRoot === '' || normalizedRoot === '(default)';
}

export function workspaceRootLabel(root: string): string {
  if (isFallbackWorkspaceRoot(root)) {
    return FALLBACK_WORKSPACE_LABEL;
  }
  const parts = root.split(/[\\/]+/).filter(Boolean);
  return parts.slice(-2).join(' / ');
}

export function workspaceRootTitle(root: string): string {
  return isFallbackWorkspaceRoot(root) ? FALLBACK_WORKSPACE_LABEL : root;
}
