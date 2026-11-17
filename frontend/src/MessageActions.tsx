import { useState } from 'react';
import { useLocale } from './i18n/index.ts';
import { Button } from './ui/Button';

/** Per-message affordances under an assistant reply: Copy (the raw markdown) and,
 *  on the latest reply, Retry (regenerate the last turn). Hover-revealed, flat,
 *  ghost buttons — no new chrome weight. */
export default function MessageActions({
  text,
  onRetry,
  showRetry
}: {
  text: string;
  onRetry?: () => void;
  showRetry?: boolean;
}) {
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle');
  const { t } = useLocale();

  function resetCopyStatus() {
    window.setTimeout(() => setCopyStatus('idle'), 1200);
  }

  async function copy() {
    if (!navigator.clipboard) {
      setCopyStatus('failed');
      resetCopyStatus();
      return;
    }

    try {
      await navigator.clipboard.writeText(text);
      setCopyStatus('copied');
    } catch {
      setCopyStatus('failed');
    }
    resetCopyStatus();
  }

  return (
    <div className="msg-actions">
      <Button variant="quiet" className="msg-action" onClick={copy}>
        {copyStatus === 'copied' ? t('chat.copied') : copyStatus === 'failed' ? t('chat.copyUnavailable') : t('chat.copy')}
      </Button>
      {showRetry && onRetry && (
        <Button variant="quiet" className="msg-action" onClick={onRetry}>
          {t('chat.retry')}
        </Button>
      )}
    </div>
  );
}
