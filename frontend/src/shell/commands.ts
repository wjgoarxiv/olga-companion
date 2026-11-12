import type { I18nKey } from '../i18n/index.ts';
import type { ShellCommandId } from './keymap';

export interface ShellCommand {
  readonly id: ShellCommandId;
  readonly labelKey: I18nKey;
  readonly keywords?: string;
}

/** Palette command registry. Labels resolve through the dictionary; running
    a command only navigates or toggles chrome. The Run entries open the Run
    view preview path — they never approve or start a run. */
export const SHELL_COMMANDS: readonly ShellCommand[] = [
  { id: 'go-case', labelKey: 'shell.cmdGoCase' },
  { id: 'go-results', labelKey: 'shell.cmdGoResults' },
  { id: 'go-runs', labelKey: 'shell.cmdGoRuns' },
  { id: 'go-settings', labelKey: 'shell.cmdGoSettings' },
  { id: 'toggle-dock', labelKey: 'shell.cmdToggleDock' },
  { id: 'toggle-panel', labelKey: 'shell.cmdTogglePanel' },
  { id: 'validate', labelKey: 'shell.cmdValidate' },
  { id: 'preview-run', labelKey: 'shell.cmdPreviewRun' },
  { id: 'open-run', labelKey: 'shell.cmdOpenRun' },
  { id: 'open-palette', labelKey: 'shell.cmdPalette' },
  { id: 'toggle-theme', labelKey: 'shell.cmdToggleTheme' },
  { id: 'switch-language', labelKey: 'shell.cmdSwitchLanguage' },
  { id: 'show-shortcuts', labelKey: 'shell.cmdShortcuts' },
  { id: 'show-guide', labelKey: 'shell.cmdShowGuide' },
  { id: 'create-fluid-table', labelKey: 'tabbanner.create' },
];
