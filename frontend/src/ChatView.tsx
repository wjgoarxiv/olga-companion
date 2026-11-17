import { useEffect, useRef, type RefObject } from 'react';
import { Plus } from 'lucide-react';
import ApprovalCard from './ApprovalCard';
import EmptyState from './EmptyState';
import ResizeCoachmark from './shell/ResizeCoachmark.tsx';
import SimulationGuide from './SimulationGuide';
import Markdown from './Markdown';
import MessageActions from './MessageActions';
import { describeChatError } from './chatErrorPresentation';
import { draftToShow } from './chatDraft';
import { QueuedMessages } from './QueuedMessages';
import SessionMenu from './SessionMenu';
import ToolUnit from './ToolUnit';
import { Button } from './ui/Button';
import { useLocale, type TranslateFn } from './i18n/index.ts';
import { OperationStatus } from './ui/OperationStatus';
import { ActivityLoader } from './ui/ActivityLoader';
import type { SessionMeta } from './session';
import type { TimelineItem } from './timeline';
import type { ApprovalRequest } from './types';
import type { ChatActivityPresentation } from './progressPresentation';
import type { QueuedMessage } from './activeWorkQueue';

interface ChatViewProps {
  readonly activeCaseName: string | null;
  readonly atBottom: boolean;
  readonly busy: boolean;
  readonly draft: string;
  readonly activity: ChatActivityPresentation | null;
  readonly healthReady: boolean;
  readonly providerReady: boolean;
  readonly onOpenWorkspace: () => void;
  readonly onOpenSettings: () => void;
  readonly input: string;
  readonly lastUserText: string;
  readonly pendingApproval?: ApprovalRequest;
  readonly queued: readonly QueuedMessage[];
  readonly scrollRef: RefObject<HTMLDivElement | null>;
  readonly sessionId: string;
  readonly sessions: readonly SessionMeta[];
  readonly timeline: readonly TimelineItem[];
  readonly workspaceGeneration: number;
  readonly workspaceCaseCount: number;
  readonly newCaseStarter: string;
  readonly onApprove: (request: ApprovalRequest) => void | Promise<void>;
  readonly onRecoverApproval: (request: ApprovalRequest) => void | Promise<void>;
  readonly onDeleteChat: (id: string) => void | Promise<void>;
  readonly onInput: (value: string) => void;
  readonly onEditQueued: (id: string, message: string) => void;
  readonly onLoadSession: (id: string) => void | Promise<void>;
  readonly onNewChat: () => void | Promise<void>;
  readonly onPickStarter: (message: string) => void | Promise<void>;
  readonly onRegenerate: () => void | Promise<void>;
  readonly onReject: (request: ApprovalRequest) => void | Promise<void>;
  readonly onRejectAndApplySteer: (request: ApprovalRequest) => void | Promise<void>;
  readonly onRemoveQueued: (id: string) => void;
  readonly onRetryError: () => void;
  readonly onScroll: () => void;
  readonly onScrollToBottom: () => void;
  readonly onStop: () => void;
  readonly onSteerNow: () => void;
  readonly onQueueNext: () => void;
  readonly onSubmit: () => void;
}

function assertNever(value: never): never {
  throw new Error(`Unhandled timeline item: ${JSON.stringify(value)}`);
}

function renderTimelineItem(
  item: TimelineItem,
  idx: number,
  props: Pick<ChatViewProps, 'busy' | 'lastUserText' | 'onApprove' | 'onOpenWorkspace' | 'onRecoverApproval' | 'onRegenerate' | 'onReject' | 'onRetryError' | 'timeline' | 'workspaceGeneration'>,
  t: TranslateFn
) {
  switch (item.kind) {
    case 'user':
      return <div key={item.id} className="msg user"><div className="bubble user">{item.text}</div></div>;
    case 'assistant':
      return (
        <div key={item.id} className="msg assistant">
          <div className="bubble assistant"><Markdown text={item.text} /></div>
          <MessageActions text={item.text} onRetry={props.onRegenerate} showRetry={idx === props.timeline.length - 1 && !props.busy} />
        </div>
      );
    case 'thinking':
      return (
        <details key={item.id} className="thinking">
          <summary>{t('chat.thinking')}</summary>
          <div className="thinking-body"><Markdown text={item.text} /></div>
        </details>
      );
    case 'tool':
      return <ToolUnit key={item.id} name={item.name} status={item.status} result={item.result} currentWorkspaceGeneration={props.workspaceGeneration} />;
    case 'approval':
      return <ApprovalCard key={item.id} request={item.request} onApprove={props.onApprove} onRecover={props.onRecoverApproval} onReject={props.onReject} pending={props.busy} resolved={item.resolved} resolution={item.resolution} lifecycle={item.lifecycle} recoverable={item.recoverable} detail={item.detail} result={item.result} />;
    case 'error': {
      const described = describeChatError(item.text);
      return (
        <OperationStatus
          key={item.id}
          className="error-row"
          tone="error"
          title={t(described.titleKey)}
          detail={
            <span className="chat-error-detail">
              <details>
                <summary>{t(described.detailsKey)}</summary>
                <pre>{described.displayText}</pre>
              </details>
            </span>
          }
          action={described.recovery === 'open-history'
            ? <Button variant="secondary" className="open-history" onClick={props.onOpenWorkspace}>{t('chat.openRunHistory')}</Button>
            : props.lastUserText
              ? <Button variant="secondary" className="retry" onClick={props.onRetryError} disabled={props.busy}>{t(described.recovery === 'ask-again' ? 'chat.retryAskAgain' : 'chat.retry')}</Button>
              : undefined}
        />
      );
    }
    default:
      return assertNever(item);
  }
}

function latestIntakeEvidence(timeline: readonly TimelineItem[]): Record<string, unknown> | null {
  for (let index = timeline.length - 1; index >= 0; index -= 1) {
    const item = timeline[index];
    if (item.kind === 'tool' && (item.name === 'case_spec_validate' || item.name === 'case_spec_compile')) {
      const normalized = item.result?.normalized;
      if (normalized && typeof normalized === 'object' && !Array.isArray(normalized)) {
        return normalized as Record<string, unknown>;
      }
    }
  }
  return null;
}

export function ChatView(props: ChatViewProps) {
  const { t } = useLocale();
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const draftRef = useRef<HTMLDetailsElement>(null);
  const draftBodyRef = useRef<HTMLDivElement>(null);
  const guide = <SimulationGuide
    activeCaseName={props.activeCaseName} busy={props.busy}
    healthReady={props.healthReady} providerReady={props.providerReady} hasDraft={Boolean(props.input.trim())}
    newCaseStarter={props.newCaseStarter} intakeEvidence={latestIntakeEvidence(props.timeline)}
    compact={props.timeline.length > 0}
    onOpenWorkspace={props.onOpenWorkspace} onOpenSettings={props.onOpenSettings}
    onDraft={(prompt) => { if (props.input.trim()) return; props.onInput(prompt); composerRef.current?.focus(); }}
  />;
  const followDraft = () => {
    const body = draftBodyRef.current;
    if (body) body.scrollTop = body.scrollHeight;
    if (draftRef.current?.open && props.atBottom) props.onScrollToBottom();
  };
  useEffect(followDraft, [props.draft]);
  useEffect(() => {
    if (props.timeline.length === 0) props.scrollRef.current?.scrollTo({ top: 0 });
  }, [props.scrollRef, props.timeline.length]);

  return (
    <section className="chat" aria-label={t('chat.conversation')}>
      <div className="chat-head">
        <div className="chat-head-copy">
          <strong>{t('chat.conversation')}</strong>
        </div>
        <div className="chat-head-actions" role="group" aria-label={t('chat.conversationActions')}>
          <Button variant="quiet" className="new-chat" icon={<Plus size={15} strokeWidth={1.9} />} onClick={() => { void props.onNewChat(); }} disabled={props.busy} aria-label={t('chat.startNewChat')} title={t('chat.startNewChat')}>{t('chat.newChat')}</Button>
          <SessionMenu sessions={props.sessions} currentId={props.sessionId} busy={props.busy} onSelect={(id) => { void props.onLoadSession(id); }} onDelete={(id) => { void props.onDeleteChat(id); }} />
        </div>
      </div>
      <div className={'timeline' + (props.timeline.length === 0 ? ' empty' : '')} ref={props.scrollRef} onScroll={props.onScroll} data-testid="chat-timeline">
        {props.timeline.length === 0 && !props.busy && props.healthReady && (
          <ResizeCoachmark approvalActive={props.pendingApproval != null} />
        )}
        {props.timeline.length === 0 && (
          <EmptyState
            activeCaseName={props.activeCaseName}
            workspaceCaseCount={props.workspaceCaseCount}
            onPick={props.onPickStarter}
            disabled={props.busy || !props.healthReady}
          >{guide}</EmptyState>
        )}
        {props.timeline.length > 0 && guide}
        {props.timeline.map((item, idx) => renderTimelineItem(item, idx, props, t))}
        {props.busy && draftToShow(props.draft) && (
          <details className="draft-toggle" data-testid="draft-toggle" ref={draftRef} onToggle={followDraft}>
            <summary>{t('chat.draft.show')}</summary>
            <p className="draft-note">{t('chat.draft.unconfirmed')}</p>
            <div className="draft-body" ref={draftBodyRef} role="region" aria-label={t('chat.draft.unconfirmed')} aria-live="off" tabIndex={0}>
              {draftToShow(props.draft)}
            </div>
          </details>
        )}
        {props.busy && props.activity && (
          <div data-testid="working">
            <ActivityLoader loadingLabel={props.activity.label} detail={t('chat.elapsed', { seconds: (props.activity.elapsed_ms / 1000).toFixed(1) })} />
          </div>
        )}
      </div>
      {props.timeline.length > 0 && !props.atBottom && (
        <div style={{ position: 'sticky', bottom: 8, display: 'flex', justifyContent: 'center', zIndex: 1 }}>
          <Button
            variant="secondary"
            onClick={props.onScrollToBottom}
            aria-label={t('chat.recentChatAria')}
          >
            <span aria-hidden="true">↓</span> {t('chat.recentChat')}
          </Button>
        </div>
      )}
      <QueuedMessages
        items={props.queued}
        pendingApproval={props.pendingApproval}
        onEdit={props.onEditQueued}
        onRejectAndApplySteer={(request) => { void props.onRejectAndApplySteer(request); }}
        onRemove={props.onRemoveQueued}
      />
      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          if (props.healthReady && props.input.trim()) props.onSubmit();
        }}
      >
        <label htmlFor="chat-message" className="composer-label">{t('composer.question')}</label>
        <textarea
          ref={composerRef}
          id="chat-message"
          aria-label={t('composer.questionLabel')}
          aria-describedby="chat-composer-hint"
          aria-keyshortcuts="Control+Enter Meta+Enter"
          rows={3}
          value={props.input}
          onChange={(event) => props.onInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== 'Enter' || !(event.ctrlKey || event.metaKey) || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return;
            event.preventDefault();
            // Idle: send. Busy: the controller queues it for the next turn instead.
            if (props.healthReady && props.input.trim()) event.currentTarget.form?.requestSubmit();
          }}
          placeholder={props.healthReady ? t('composer.placeholderReady') : t('composer.placeholderConnecting')}
          disabled={!props.healthReady}
          data-testid="chat-input"
        />
        <div className="composer-footer">
          <span id="chat-composer-hint">{t('composer.hint')}</span>
          <div className="composer-actions">
            <Button variant="quiet" aria-label={t('composer.clearAction')} disabled={!props.input} onClick={() => { props.onInput(''); composerRef.current?.focus(); }}>{t('composer.clear')}</Button>
        {props.busy ? (
          <div className="composer-active-actions">
            {props.input.trim() && (
              <>
                <Button variant="secondary" onClick={props.onSteerNow}>{t('chat.steerNow')}</Button>
                <Button variant="quiet" onClick={props.onQueueNext}>{t('chat.queueNext')}</Button>
              </>
            )}
            <Button
              variant="secondary"
              className="stop"
              onClick={props.onStop}
              disabled={props.activity?.can_cancel === false}
            >
              {t('chat.stopAnswer')}
            </Button>
          </div>
        ) : (
          <Button type="submit" variant="primary" disabled={!props.healthReady || !props.input.trim()}>{t('composer.send')}</Button>
        )}
          </div>
        </div>
      </form>
    </section>
  );
}
