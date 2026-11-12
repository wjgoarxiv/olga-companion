import { useEffect, useRef, useSyncExternalStore, type ReactElement } from 'react';
import { useLocale } from '../i18n/index.ts';
import '../styles/boot.css';

export type ToastInput = {
  kind: string;
  title: string;
  body?: string;
  count?: number;
  onOpen?: () => void;
};

export type Toast = ToastInput & { id: number };

const TOAST_DISMISS_MS = 6_000;

let toastSeq = 0;
let current: readonly Toast[] = [];
const listeners = new Set<() => void>();

function announce(): void {
  for (const listener of listeners) listener();
}

export function pushToast(input: ToastInput): number {
  toastSeq += 1;
  const toast: Toast = { ...input, id: toastSeq };
  current = [...current, toast].slice(-4);
  announce();
  return toast.id;
}

export function dismissToast(id: number): void {
  const next = current.filter((toast) => toast.id !== id);
  if (next.length === current.length) return;
  current = next;
  announce();
}

function subscribeToasts(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function peekToasts(): readonly Toast[] {
  return current;
}

export function useToasts(): readonly Toast[] {
  return useSyncExternalStore(subscribeToasts, peekToasts, peekToasts);
}

export default function ToastQueue(): ReactElement {
  const { t } = useLocale();
  const toasts = useToasts();
  const scheduledRef = useRef(new Set<number>());
  useEffect(() => {
    for (const toast of toasts) {
      if (scheduledRef.current.has(toast.id)) continue;
      scheduledRef.current.add(toast.id);
      window.setTimeout(() => {
        scheduledRef.current.delete(toast.id);
        // Away toasts must not vanish unseen: while the window has no focus
        // the dismissal waits for its return instead of firing on the timer.
        try {
          if (typeof document !== 'undefined' && document.hasFocus && !document.hasFocus()) {
            window.addEventListener('focus', () => dismissToast(toast.id), { once: true });
            return;
          }
        } catch {
          // A blocked focus query falls through to the timed dismissal.
        }
        dismissToast(toast.id);
      }, TOAST_DISMISS_MS);
    }
  }, [toasts]);
  if (toasts.length === 0) return <></>;
  return (
    <div className="toast-queue" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className="toast">
          <button
            type="button"
            className="toast-body"
            onClick={() => {
              try {
                toast.onOpen?.();
              } finally {
                dismissToast(toast.id);
              }
            }}
          >
            <span className="toast-title">
              {toast.title}
              {toast.count && toast.count > 1 ? ` ×${toast.count}` : ''}
            </span>
            {toast.body && <span className="toast-text">{toast.body}</span>}
          </button>
          <button
            type="button"
            className="toast-close"
            aria-label={t('notify.dismiss')}
            onClick={() => dismissToast(toast.id)}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
