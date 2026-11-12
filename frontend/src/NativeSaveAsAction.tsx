import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createNativeDialogRequestId } from './nativeDialogRequest';
import { scheduleFocusReturn } from './focusReturn';
import { createNativeDialogLifecycle, type NativeDialogHandle, type NativeDialogLifecycle } from './nativeDialogLifecycle';
import * as session from './session';
import { useLocale } from './i18n/index.ts';
import type { TranslateFn } from './i18n/index.ts';
import { Button } from './ui/Button';
import { OperationStatus, type OperationStatusTone } from './ui/OperationStatus';
import { Receipt } from './ui/Receipt';

type SaveNotice = {
  readonly tone: OperationStatusTone;
  readonly title: string;
  readonly detail: string;
};

function formatBytes(size: number, t: TranslateFn): string {
  if (size < 1024) return t('saveas.bytesB', { value: size });
  if (size < 1024 * 1024) {
    const kb = (size / 1024).toFixed(1);
    return t('saveas.bytesKB', { value: kb });
  }
  const mb = (size / (1024 * 1024)).toFixed(1);
  return t('saveas.bytesMB', { value: mb });
}

export default function NativeSaveAsAction({ artifact, label }: { readonly artifact: string; readonly label: string }) {
  const { t } = useLocale();
  const [saving, setSaving] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [saved, setSaved] = useState<{ basename: string; size: number } | null>(null);
  const [notice, setNotice] = useState<SaveNotice | null>(null);
  const [recoveryId, setRecoveryId] = useState<string | null>(null);
  const [recoveryStatus, setRecoveryStatus] = useState<session.SaveAsRecoveryStatus | null>(null);
  const [recoveryLoading, setRecoveryLoading] = useState(false);
  const pendingRequestRef = useRef<{ requestId: string; handle: NativeDialogHandle } | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const focusOwnerRef = useRef<HTMLElement | null>(null);
  const focusReturnPendingRef = useRef(false);
  const recoveryAbortRef = useRef<AbortController | null>(null);
  const lifecycleRef = useRef<NativeDialogLifecycle | null>(null);
  lifecycleRef.current ??= createNativeDialogLifecycle((requestId, options) => (
    session.cancelNativeDialog(requestId, options)
  ));
  const lifecycle = lifecycleRef.current;

  function stableSaveFocusOwner(): HTMLElement | null {
    return focusOwnerRef.current?.isConnected
      ? focusOwnerRef.current
      : document.querySelector<HTMLElement>('[aria-current="page"]');
  }

  useLayoutEffect(() => {
    if (saving || !focusReturnPendingRef.current) return;
    focusReturnPendingRef.current = false;
    return scheduleFocusReturn(previousFocusRef.current, undefined, stableSaveFocusOwner);
  }, [notice, saved, saving]);

  useEffect(() => {
    lifecycle.mount();
    return () => {
      recoveryAbortRef.current?.abort();
      const cancelledRequestId = lifecycle.dispose();
      if (cancelledRequestId) {
        scheduleFocusReturn(previousFocusRef.current, undefined, stableSaveFocusOwner);
      }
    };
  }, [lifecycle]);

  function acceptTerminal(handle: NativeDialogHandle): boolean {
    if (!lifecycle.markTerminal(handle)) return false;
    if (pendingRequestRef.current?.handle === handle) pendingRequestRef.current = null;
    if (lifecycle.isDisposed()) return false;
    focusReturnPendingRef.current = true;
    setSaving(false);
    setCancelling(false);
    return true;
  }

  async function save() {
    if (pendingRequestRef.current || lifecycle.isDisposed()) return;
    recoveryAbortRef.current?.abort();
    recoveryAbortRef.current = null;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    focusOwnerRef.current = previousFocusRef.current?.closest<HTMLElement>('.receipt') ?? null;
    setNotice(null);
    setSaved(null);
    setRecoveryId(null);
    setRecoveryStatus(null);
    setRecoveryLoading(false);
    let requestId: string;
    try {
      requestId = createNativeDialogRequestId();
    } catch (error) {
      if (lifecycle.isDisposed()) return;
      focusReturnPendingRef.current = true;
      setNotice({ tone: 'error', title: t('saveas.failed'), detail: error instanceof Error ? error.message : String(error) });
      return;
    }
    const handle = lifecycle.begin(requestId);
    pendingRequestRef.current = { requestId, handle };
    setSaving(true);
    try {
      const result = await session.saveArtifactAs(requestId, artifact);
      if (!acceptTerminal(handle)) return;
      if (result.status === 'selected') {
        setSaved({ basename: result.basename, size: result.size });
      } else if (result.status === 'cancelled') {
        setNotice({ tone: 'info', title: t('saveas.cancelledTitle'), detail: t('saveas.cancelledDetail') });
      } else {
        setNotice({ tone: 'info', title: t('saveas.unavailable'), detail: result.reason });
      }
    } catch (error) {
      if (!acceptTerminal(handle)) return;
      if (error instanceof session.SaveAsRecoveryError) {
        setRecoveryId(error.recoveryId);
        setNotice({ tone: 'error', title: t('saveas.recoveryRequired'), detail: t('saveas.recoveryDetail', { message: error.message, recoveryId: error.recoveryId }) });
      } else {
        setNotice({ tone: 'error', title: t('saveas.failed'), detail: error instanceof Error ? error.message : String(error) });
      }
    }
  }

  async function checkRecoveryStatus() {
    if (!recoveryId || lifecycle.isDisposed()) return;
    recoveryAbortRef.current?.abort();
    const controller = new AbortController();
    recoveryAbortRef.current = controller;
    setRecoveryLoading(true);
    try {
      const status = await session.fetchSaveAsRecoveryStatus(recoveryId, controller.signal);
      if (!controller.signal.aborted && !lifecycle.isDisposed()) setRecoveryStatus(status);
    } catch (error) {
      if (!controller.signal.aborted && !lifecycle.isDisposed()) {
        setNotice({ tone: 'error', title: t('saveas.recoveryUnavailable'), detail: error instanceof Error ? error.message : String(error) });
      }
    } finally {
      if (recoveryAbortRef.current === controller) {
        recoveryAbortRef.current = null;
        if (!lifecycle.isDisposed()) setRecoveryLoading(false);
      }
    }
  }

  async function cancel() {
    const pending = pendingRequestRef.current;
    if (!pending || cancelling) return;
    setCancelling(true);
    try {
      const result = await session.cancelNativeDialog(pending.requestId);
      if (lifecycle.isDisposed() || pendingRequestRef.current?.handle !== pending.handle) return;
      if (result.status === 'cancelled') {
        if (!acceptTerminal(pending.handle)) return;
        setNotice({ tone: 'info', title: t('saveas.cancelledTitle'), detail: t('saveas.dialogClosedDetail') });
      } else {
        setNotice({ tone: 'info', title: t('saveas.cancelUnavailable'), detail: result.reason });
      }
    } catch (error) {
      if (!lifecycle.isDisposed() && pendingRequestRef.current?.handle === pending.handle) {
        setNotice({ tone: 'error', title: t('saveas.cancelFailed'), detail: error instanceof Error ? error.message : String(error) });
      }
    } finally {
      if (!lifecycle.isDisposed() && pendingRequestRef.current?.handle === pending.handle) setCancelling(false);
    }
  }

  return (
    <div className="native-save-action">
      <Button variant="secondary" onClick={() => { void save(); }} disabled={saving}>{label}</Button>
      {saving && (
        <OperationStatus
          tone="busy"
          title={t('saveas.openTitle')}
          detail={t('saveas.openDetail')}
          action={<Button variant="quiet" onClick={() => { void cancel(); }} busy={cancelling} busyLabel={t('saveas.cancelling')}>{t('saveas.cancel')}</Button>}
        />
      )}
      {!saving && saved && <Receipt title={t('saveas.completeTitle')} meta={`${saved.basename} · ${formatBytes(saved.size, t)}`} />}
      {!saving && notice && <OperationStatus tone={notice.tone} title={notice.title} detail={notice.detail} />}
      {!saving && recoveryId && (
        <Button variant="secondary" onClick={() => { void checkRecoveryStatus(); }} busy={recoveryLoading} busyLabel={t('saveas.checkingRecovery')}>
          {t('saveas.checkRecovery')}
        </Button>
      )}
      {!saving && recoveryStatus && (
        <Receipt
          title={t('saveas.recoveryTitle')}
          meta={t('saveas.recoveryMeta', { basename: recoveryStatus.basename, backup: recoveryStatus.backup_available ? t('saveas.verifiedBackup') : t('saveas.backupUnavailable'), time: recoveryStatus.time })}
        >
          <span>{recoveryStatus.backup_available
            ? t('saveas.keepRecovery', { id: recoveryStatus.id })
            : t('saveas.noBackup', { id: recoveryStatus.id })}</span>
        </Receipt>
      )}
    </div>
  );
}
