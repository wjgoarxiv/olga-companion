import { useEffect, useRef } from 'react';
import { useLocale } from './i18n/index.ts';
import {
  AWAY_COLLAPSE_WINDOW_MS,
  createAwayCollapse,
  createAwayNotifier,
  loadAwayNotifyEnabled,
  newTerminalRuns,
  shouldNotifyAway,
  shouldSuppressChatDone,
} from './awayNotify.mjs';
import { dismissToast, pushToast } from './ui/Toast';
import { peekFoundUpdate, subscribeFoundUpdate } from './updateAutoCheck.mjs';
import type { TimelineItem } from './timeline';

type AwayOpeners = {
  onOpenRun: (runId: string) => void;
  onOpenApproval: () => void;
  onOpenChat: () => void;
  onOpenUpdates: () => void;
};

/** Watches run/approval/chat/update signals and notifies only while the
 *  user is in another window: document.hidden or the window unfocused, with
 *  the Settings toggle on. Focused use stays silent — the event is visible. */
export function useAwayNotifications(
  timeline: readonly TimelineItem[],
  busy: boolean,
  hasPendingApproval: boolean,
  openers: AwayOpeners,
): void {
  const { t } = useLocale();
  const focusedRef = useRef(
    typeof document === 'undefined' || typeof document.hasFocus !== 'function'
      ? true
      : document.hasFocus(),
  );
  const collapseRef = useRef(createAwayCollapse());
  const openToastRef = useRef(new Map<string, number>());
  const seenRunsRef = useRef(new Set<string>());
  const seededRef = useRef(false);
  const lastRunNotifiedAtRef = useRef<number | null>(null);
  const latestApprovalRef = useRef(hasPendingApproval);
  latestApprovalRef.current = hasPendingApproval;
  const prevBusyRef = useRef(busy);
  const prevApprovalRef = useRef(hasPendingApproval);
  const openersRef = useRef(openers);
  openersRef.current = openers;
  const textRef = useRef({ runFinished: '', runFailed: '', approval: '', chatDone: '', updateReady: '' });
  textRef.current = {
    runFinished: t('notify.runFinished'),
    runFailed: t('notify.runFailed'),
    approval: t('notify.approvalNeeded'),
    chatDone: t('notify.chatDone'),
    updateReady: t('notify.updateReady'),
  };

  useEffect(() => {
    const onBlur = () => {
      focusedRef.current = false;
    };
    const onFocus = () => {
      focusedRef.current = true;
    };
    window.addEventListener('blur', onBlur);
    window.addEventListener('focus', onFocus);
    return () => {
      window.removeEventListener('blur', onBlur);
      window.removeEventListener('focus', onFocus);
    };
  }, []);

  function fire(kind: string, title: string, onOpen: () => void): void {
    if (
      !shouldNotifyAway({
        hidden: document.hidden,
        focused: focusedRef.current,
        enabled: loadAwayNotifyEnabled(),
      })
    ) {
      return;
    }
    const slot = collapseRef.current.push(kind);
    void createAwayNotifier({
      showToast: (entry) => {
        const open = openToastRef.current.get(entry.kind);
        if (open !== undefined) dismissToast(open);
        openToastRef.current.set(entry.kind, pushToast(entry));
      },
    })({ kind, title, count: slot.count, onOpen });
  }

  // Run patrols report terminal states in the timeline: completed and failed
  // both notify, with the run's output one click away. The first populated
  // timeline is a restore, so it seeds silently and an old run never pages.
  useEffect(() => {
    const seeding = !seededRef.current;
    if (seeding && timeline.length === 0) return;
    const text = textRef.current;
    const openers = openersRef.current;
    for (const { runId, state } of newTerminalRuns(timeline, seenRunsRef.current)) {
      if (seeding) continue;
      if (state === 'completed') {
        fire('run-finished', text.runFinished, () => openers.onOpenRun(runId));
        lastRunNotifiedAtRef.current = Date.now();
      } else if (state === 'failed') {
        fire('run-failed', text.runFailed, () => openers.onOpenRun(runId));
        lastRunNotifiedAtRef.current = Date.now();
      }
    }
    seededRef.current = true;
  });

  useEffect(() => {
    if (hasPendingApproval && !prevApprovalRef.current) {
      const text = textRef.current;
      fire('approval-needed', text.approval, () => openersRef.current.onOpenApproval());
    }
    prevApprovalRef.current = hasPendingApproval;
  });

  useEffect(() => {
    if (prevBusyRef.current && !busy) {
      // An approval pause ends the turn too, but the approval toast already
      // covers it; so does a run finish that just notified.
      if (
        !latestApprovalRef.current
        && !shouldSuppressChatDone({
          lastRunNotifiedAt: lastRunNotifiedAtRef.current,
          windowMs: AWAY_COLLAPSE_WINDOW_MS,
        })
      ) {
        const text = textRef.current;
        fire('chat-done', text.chatDone, () => openersRef.current.onOpenChat());
      }
    }
    prevBusyRef.current = busy;
  });

  useEffect(() => subscribeFoundUpdate(() => {
    if (!peekFoundUpdate()) return;
    const text = textRef.current;
    fire('update-ready', text.updateReady, () => openersRef.current.onOpenUpdates());
  }), []);
}
