export type ShellCommandId =
  | 'go-case'
  | 'go-results'
  | 'go-runs'
  | 'go-settings'
  | 'toggle-dock'
  | 'toggle-panel'
  | 'validate'
  | 'preview-run'
  | 'open-run'
  | 'open-palette'
  | 'toggle-theme'
  | 'switch-language'
  | 'show-shortcuts'
  | 'show-guide'
  | 'create-fluid-table'
  | 'open-examples';

export interface KeyEventShape {
  readonly key: string;
  readonly ctrlKey: boolean;
  readonly metaKey: boolean;
}

/** Global workbench shortcuts. Typing surfaces own their keys: view jumps
    and dock/panel toggles stay inert inside inputs, textareas and selects.
    F5 opens the Run preview only and never executes anything. */
export function matchShellShortcut(event: KeyEventShape): ShellCommandId | null {
  const modified = event.ctrlKey || event.metaKey;
  const tag = typeof document !== 'undefined' && document.activeElement
    ? document.activeElement.tagName
    : '';
  const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
  if (modified && event.key.toLowerCase() === 'k') return 'open-palette';
  if (modified && !typing) {
    if (event.key === '1') return 'go-case';
    if (event.key === '2') return 'go-results';
    if (event.key === '3') return 'go-runs';
    if (event.key === '4') return 'go-settings';
    if (event.key.toLowerCase() === 'j') return 'toggle-dock';
  }
  if (event.ctrlKey && event.key === '`' && !typing) return 'toggle-panel';
  if (event.key === 'F5') return 'preview-run';
  if (event.key === '?' && !typing) return 'show-shortcuts';
  if (event.key === 'Escape') return null;
  return null;
}
