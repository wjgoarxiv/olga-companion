import { useEffect, useRef } from 'react';
import { Kbd } from '../ui/Kbd';
import { useLocale } from '../i18n/index.ts';

const ROWS: readonly { readonly keys: readonly string[]; readonly labelKey: 'shell.cmdPalette' | 'shell.cmdGoCase' | 'shell.cmdToggleDock' | 'shell.cmdTogglePanel' | 'shell.cmdPreviewRun' | 'shell.cmdShortcuts' }[] = [
  { keys: ['Ctrl', 'K'], labelKey: 'shell.cmdPalette' },
  { keys: ['Ctrl', '1…4'], labelKey: 'shell.cmdGoCase' },
  { keys: ['Ctrl', 'J'], labelKey: 'shell.cmdToggleDock' },
  { keys: ['Ctrl', '`'], labelKey: 'shell.cmdTogglePanel' },
  { keys: ['F5'], labelKey: 'shell.cmdPreviewRun' },
  { keys: ['?'], labelKey: 'shell.cmdShortcuts' },
];

const RESIZE_ROWS: readonly { readonly keys: readonly string[]; readonly labelKey: 'resize.scNudge' | 'resize.scLarge' | 'resize.scEnds' }[] = [
  { keys: ['←', '→', '↑', '↓'], labelKey: 'resize.scNudge' },
  { keys: ['Shift', '←', '→', '↑', '↓'], labelKey: 'resize.scLarge' },
  { keys: ['Home', 'End'], labelKey: 'resize.scEnds' },
];

export default function ShortcutsDialog({ onClose }: { readonly onClose: () => void }) {
  const { t } = useLocale();
  const closeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    closeRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    }
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  return (
    <div className="wb-sheet-scrim" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <div role="dialog" aria-modal="true" aria-label={t('shell.shortcutsTitle')} className="wb-sheet">
        <h2 className="wb-sheet-title">{t('shell.shortcutsTitle')}</h2>
        <table className="ui-table" aria-label={t('shell.shortcutsTitle')}>
          <tbody>
            {ROWS.map((row) => (
              <tr key={row.labelKey}>
                <td><Kbd>{row.keys.join(' + ')}</Kbd></td>
                <td>{t(row.labelKey)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <h3 className="wb-sheet-title">{t('resize.shortcutsTitle')}</h3>
        <table className="ui-table" aria-label={t('resize.shortcutsTitle')}>
          <tbody>
            {RESIZE_ROWS.map((row) => (
              <tr key={row.labelKey}>
                <td><Kbd>{row.keys.join(' + ')}</Kbd></td>
                <td>{t(row.labelKey)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="wb-sheet-actions">
          <button ref={closeRef} type="button" className="wb-btn" onClick={onClose}>{t('shell.close')}</button>
        </div>
      </div>
    </div>
  );
}
