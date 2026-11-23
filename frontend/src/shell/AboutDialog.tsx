import { useEffect, useRef, type RefObject } from 'react';
import { useLocale } from '../i18n/index.ts';

export const ABOUT_OPEN_EVENT = 'olga:open-about';

/** The palette entry opens the dialog through this event, so App does not hold its state. */
export function requestAboutOpen(): void {
  window.dispatchEvent(new CustomEvent(ABOUT_OPEN_EVENT));
}

let aboutOpen = false;

/** The workbench shortcuts stay quiet while About is open, so nothing opens over or behind it. */
export function isAboutOpen(): boolean {
  return aboutOpen;
}

/** Who made the app, its licence, and that it is not an SLB product (security review A5). */
export default function AboutDialog({ onClose, fallbackFocus }: {
  readonly onClose: () => void;
  readonly fallbackFocus?: RefObject<HTMLButtonElement | null>;
}) {
  const { t } = useLocale();
  const closeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    aboutOpen = true;
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      } else if (event.key === 'Tab') {
        // Close is the only control, so Tab keeps focus on it.
        event.preventDefault();
        closeRef.current?.focus();
      }
    }
    document.addEventListener('keydown', onKey, true);
    return () => {
      aboutOpen = false;
      document.removeEventListener('keydown', onKey, true);
      // Opened from the palette, the opener is gone (focus sat on the page body); the About button takes focus instead.
      const target = returnFocus && returnFocus !== document.body && returnFocus.isConnected
        ? returnFocus
        : fallbackFocus?.current;
      target?.focus();
    };
  }, [onClose, fallbackFocus]);

  return (
    <div className="wb-sheet-scrim" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <div role="dialog" aria-modal="true" aria-labelledby="about-title" className="wb-sheet wb-about">
        <h2 id="about-title" className="wb-sheet-title">{t('about.title')}</h2>
        <table className="ui-table">
          <tbody>
            <tr><th scope="row">{t('about.version')}</th><td>v{__APP_VERSION__}</td></tr>
            <tr><th scope="row">{t('about.license')}</th><td>{t('about.licenseName')}</td></tr>
          </tbody>
        </table>
        <p>{t('about.author')}</p>
        <p>{t('about.notice')}</p>
        <p>{t('about.slb')}</p>
        <div className="wb-sheet-actions">
          <button ref={closeRef} type="button" className="wb-btn" onClick={onClose}>{t('shell.close')}</button>
        </div>
      </div>
    </div>
  );
}
