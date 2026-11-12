import { ChatView } from '../ChatView';
import type { useChatController } from '../useChatController';
import type { RuntimeState } from '../runtimeLifecycle';
import type { TranslateFn } from '../i18n/index.ts';
import { localizeActivity } from '../progressPresentation';
import ChatDock from './ChatDock';

type ChatController = ReturnType<typeof useChatController>;

export default function ChatDockView({
  open,
  onToggle,
  chat,
  runtimeOnline,
  providerReady,
  activeCaseName,
  workspaceGeneration,
  workspaceCaseCount,
  newCaseStarter,
  t,
  onSelectView,
}: {
  readonly open: boolean;
  readonly onToggle: (open: boolean) => void;
  readonly chat: ChatController;
  readonly runtimeOnline: boolean;
  readonly providerReady: boolean;
  readonly activeCaseName: string | null;
  readonly workspaceGeneration: number;
  readonly workspaceCaseCount: number;
  readonly newCaseStarter: string;
  readonly t: TranslateFn;
  readonly onSelectView: (view: 'workspace' | 'settings') => void;
}) {
  return (
    <ChatDock open={open} onToggle={onToggle}>
      <ChatView
        activity={chat.activity && localizeActivity(chat.activity, t)}
        atBottom={chat.atBottom}
        activeCaseName={activeCaseName}
        busy={chat.busy}
        draft={chat.draft}
        healthReady={runtimeOnline}
        providerReady={providerReady} onOpenWorkspace={() => onSelectView('workspace')} onOpenSettings={() => onSelectView('settings')}
        input={chat.input}
        lastUserText={chat.lastUserText}
        pendingApproval={chat.pendingApproval}
        queued={chat.queued}
        scrollRef={chat.scrollRef}
        sessionId={chat.sessionId}
        sessions={chat.sessions}
        timeline={chat.timeline}
        workspaceGeneration={workspaceGeneration}
        workspaceCaseCount={workspaceCaseCount}
        onApprove={chat.approve} onRecoverApproval={chat.recoverApproval}
        onDeleteChat={chat.deleteChat} onEditQueued={chat.editQueued}
        newCaseStarter={newCaseStarter}
        onInput={chat.setInput}
        onLoadSession={chat.loadSession}
        onNewChat={chat.newChat}
        onPickStarter={chat.send}
        onRegenerate={chat.regenerate}
        onReject={chat.reject} onRejectAndApplySteer={chat.rejectAndApplySteer}
        onRemoveQueued={chat.removeQueued}
        onRetryError={chat.retryError}
        onScroll={chat.onScroll}
        onScrollToBottom={chat.scrollToBottom}
        onStop={chat.stop} onSteerNow={chat.steerNow} onQueueNext={chat.queueNext}
        onSubmit={chat.submitInput}
      />
    </ChatDock>
  );
}
