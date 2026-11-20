import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import type { QueuedMessage } from './activeWorkQueue';
import { useLocale } from './i18n/index.ts';
import { Button } from './ui/Button';
import type { ApprovalRequest } from './types';

interface QueuedMessagesProps {
  readonly items: readonly QueuedMessage[];
  readonly pendingApproval?: ApprovalRequest;
  readonly onEdit: (id: string, message: string) => void;
  readonly onRejectAndApplySteer: (request: ApprovalRequest) => void;
  readonly onRemove: (id: string) => void;
}

function QueuedMessageRow({
  item,
  onEdit,
  onRemove,
}: {
  readonly item: QueuedMessage;
  readonly onEdit: (id: string, message: string) => void;
  readonly onRemove: (id: string) => void;
}) {
  const { t } = useLocale();
  const [draft, setDraft] = useState(item.message);
  useEffect(() => { setDraft(item.message); }, [item.id, item.message]);
  return (
    <li className={`queued-message queued-message-${item.policy}`}>
      <span className="queued-message-policy">
        {item.policy === 'steer' ? t('queue.policySteer') : t('queue.policyAfter')}
      </span>
      <input
        aria-label={t('queue.editMessage', { message: item.message })}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => {
          if (draft.trim()) onEdit(item.id, draft);
          else setDraft(item.message);
        }}
      />
      <button
        type="button"
        className="queued-message-remove"
        onClick={() => onRemove(item.id)}
        aria-label={t('queue.removeMessage', { message: item.message })}
      >
        <X aria-hidden="true" focusable="false" size={14} />
      </button>
    </li>
  );
}

export function QueuedMessages(props: QueuedMessagesProps) {
  const { t } = useLocale();
  if (props.items.length === 0) return null;
  const steerBlocked = props.pendingApproval
    && props.items.some((item) => item.policy === 'steer');
  const blockedApproval = steerBlocked ? props.pendingApproval : undefined;
  return (
    <section className="queued-messages" aria-label={t('queue.title')}>
      <header>
        <strong>{t('queue.upNext')}</strong>
        <span>{t('queue.count', { count: props.items.length })}</span>
      </header>
      <ol>
        {props.items.map((item) => (
          <QueuedMessageRow
            key={item.id}
            item={item}
            onEdit={props.onEdit}
            onRemove={props.onRemove}
          />
        ))}
      </ol>
      {blockedApproval && (
        <div className="queued-approval-conflict">
          <span>{t('queue.steerBlocked')}</span>
          <Button
            variant="secondary"
            onClick={() => props.onRejectAndApplySteer(blockedApproval)}
          >
            {t('queue.rejectSteer')}
          </Button>
        </div>
      )}
    </section>
  );
}
