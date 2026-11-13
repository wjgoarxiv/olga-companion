import { useState } from 'react';
import { MoveHorizontal } from 'lucide-react';
import { useLocale } from '../i18n/index.ts';
import { writeLocalStorage } from '../safeLocalStorage.ts';
import { Kbd } from '../ui/Kbd.tsx';
import {
  COACHMARK_DISMISS_KEY,
  readCoachmarkVisibility,
  shouldShowResizeCoachmark,
} from './resizeCoachmarkState.ts';

export default function ResizeCoachmark({ approvalActive }: { readonly approvalActive: boolean }) {
  const { t } = useLocale();
  const [dismissed, setDismissed] = useState(false);
  if (!shouldShowResizeCoachmark({ ...readCoachmarkVisibility(approvalActive), dismissed })) return null;
  return (
    <div className="resize-coachmark" data-testid="resize-coachmark" role="note">
      <MoveHorizontal size={15} strokeWidth={1.9} aria-hidden="true" />
      <div className="resize-coachmark-body">
        <strong>{t('resize.shortcutsTitle')}</strong>
        <span>{t('resize.hint')}</span>
        <span className="resize-coachmark-keys">
          <Kbd>← → ↑ ↓</Kbd>
          <Kbd>Shift</Kbd>
          <Kbd>Home End</Kbd>
        </span>
      </div>
      <button
        type="button"
        aria-label={t('shell.close')}
        onClick={() => {
          writeLocalStorage(COACHMARK_DISMISS_KEY, 'dismissed');
          setDismissed(true);
        }}
      >
        {t('shell.close')}
      </button>
    </div>
  );
}
