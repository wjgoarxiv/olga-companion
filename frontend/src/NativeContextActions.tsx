import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createNativeDialogRequestId } from './nativeDialogRequest';
import { scheduleFocusReturn } from './focusReturn';
import { createNativeDialogLifecycle, type NativeDialogHandle, type NativeDialogLifecycle } from './nativeDialogLifecycle';
import { useLocale, type I18nKey } from './i18n/index.ts';
import * as session from './session';
import { Button } from './ui/Button';
import { OperationStatus, type OperationStatusTone } from './ui/OperationStatus';

type ContextDialogKind = 'workspace' | 'case';
type DialogNotice =
  | {
      readonly kind: 'text';
      readonly tone: OperationStatusTone;
      readonly titleKey: I18nKey;
      readonly titleWordKey: I18nKey | null;
      readonly detailKey: I18nKey | null;
      readonly detailText: string;
    }
  | {
      readonly kind: 'selected';
      readonly tone: OperationStatusTone;
      readonly titleKey: I18nKey;
      readonly count: number;
      readonly activeName: string;
    };

function stableContextFocusOwner(): HTMLElement | null {
  return document.querySelector<HTMLElement>('.case-chip')
    ?? document.querySelector<HTMLElement>('[aria-current="page"]');
}

export default function NativeContextActions({
  onSelected,
  className,
  contextGeneration,
}: {
  readonly onSelected: (context: session.NativeSelectedContext) => void | Promise<void>;
  readonly className?: string;
  readonly contextGeneration: number;
}) {
  const [pendingKind, setPendingKind] = useState<ContextDialogKind | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [notice, setNotice] = useState<DialogNotice | null>(null);
  const { t } = useLocale();
  const pendingRequestRef = useRef<{ requestId: string; kind: ContextDialogKind; handle: NativeDialogHandle; contextGeneration: number } | null>(null);
  const contextGenerationRef = useRef(contextGeneration);
  contextGenerationRef.current = contextGeneration;
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const focusReturnPendingRef = useRef(false);
  const lifecycleRef = useRef<NativeDialogLifecycle | null>(null);
  lifecycleRef.current ??= createNativeDialogLifecycle((requestId, options) => (
    session.cancelNativeDialog(requestId, options)
  ));
  const lifecycle = lifecycleRef.current;

  useLayoutEffect(() => {
    if (pendingKind !== null || !focusReturnPendingRef.current) return;
    focusReturnPendingRef.current = false;
    return scheduleFocusReturn(previousFocusRef.current, undefined, stableContextFocusOwner);
  }, [notice, pendingKind]);

  useEffect(() => {
    lifecycle.mount();
    return () => {
      const cancelledRequestId = lifecycle.dispose();
      if (cancelledRequestId) {
        scheduleFocusReturn(previousFocusRef.current, undefined, stableContextFocusOwner);
      }
    };
  }, [lifecycle]);

  useEffect(() => {
    const cancelledRequestId = lifecycle.cancelForContextChange(contextGeneration);
    if (!cancelledRequestId || pendingRequestRef.current?.requestId !== cancelledRequestId) return;
    pendingRequestRef.current = null;
    focusReturnPendingRef.current = true;
    setPendingKind(null);
    setCancelling(false);
    setNotice(null);
  }, [contextGeneration, lifecycle]);

  function acceptTerminal(handle: NativeDialogHandle): boolean {
    if (!lifecycle.markTerminal(handle, contextGenerationRef.current)) return false;
    if (pendingRequestRef.current?.handle === handle) pendingRequestRef.current = null;
    if (lifecycle.isDisposed()) return false;
    focusReturnPendingRef.current = true;
    setPendingKind(null);
    setCancelling(false);
    return true;
  }

  async function start(kind: ContextDialogKind) {
    if (pendingRequestRef.current || lifecycle.isDisposed()) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setNotice(null);
    let requestId: string;
    try {
      requestId = createNativeDialogRequestId();
    } catch (error) {
      if (lifecycle.isDisposed()) return;
      focusReturnPendingRef.current = true;
      setNotice({ kind: 'text', tone: 'error', titleKey: 'native.dialogFailed', titleWordKey: null, detailKey: null, detailText: error instanceof Error ? error.message : String(error) });
      return;
    }
    const requestGeneration = contextGeneration;
    const handle = lifecycle.begin(requestId, requestGeneration);
    pendingRequestRef.current = { requestId, kind, handle, contextGeneration: requestGeneration };
    setPendingKind(kind);
    let result: session.NativeContextDialogResult;
    try {
      result = kind === 'workspace'
        ? await session.chooseNativeWorkspace(requestId, requestGeneration)
        : await session.openNativeCase(requestId, requestGeneration);
    } catch (error) {
      if (acceptTerminal(handle)) {
        setNotice({ kind: 'text', tone: 'error', titleKey: 'native.dialogFailed', titleWordKey: null, detailKey: null, detailText: error instanceof Error ? error.message : String(error) });
      }
      return;
    }
    if (!acceptTerminal(handle)) return;
    if (result.status === 'selected') {
      try {
        await onSelected(result);
        if (lifecycle.isDisposed()) return;
        setNotice({
          kind: 'selected',
          tone: 'success',
          titleKey: kind === 'workspace' ? 'native.workspaceSelected' : 'native.caseOpened',
          count: result.cases.length,
          activeName: result.active.name ?? '',
        });
      } catch (error) {
        if (!lifecycle.isDisposed()) {
          setNotice({ kind: 'text', tone: 'error', titleKey: 'native.dialogFailed', titleWordKey: null, detailKey: null, detailText: error instanceof Error ? error.message : String(error) });
        }
      }
    } else if (result.status === 'cancelled') {
      setNotice({
        kind: 'text',
        tone: 'info',
        titleKey: 'native.selectionCancelled',
        titleWordKey: kind === 'workspace' ? 'native.workspaceWord' : 'native.caseWord',
        detailKey: 'native.noContextChanged',
        detailText: '',
      });
    } else if (result.status === 'superseded') {
      setNotice(null);
    } else {
      setNotice({ kind: 'text', tone: 'info', titleKey: 'native.dialogUnavailable', titleWordKey: null, detailKey: null, detailText: result.reason });
    }
  }

  async function cancel() {
    const pending = pendingRequestRef.current;
    if (!pending || cancelling) return;
    setCancelling(true);
    try {
      const result = await session.cancelNativeDialog(pending.requestId);
      if (lifecycle.isDisposed() || pending.contextGeneration !== contextGenerationRef.current || pendingRequestRef.current?.handle !== pending.handle) return;
      if (result.status === 'cancelled') {
        if (!acceptTerminal(pending.handle)) return;
        setNotice({
          kind: 'text',
          tone: 'info',
          titleKey: 'native.selectionCancelled',
          titleWordKey: pending.kind === 'workspace' ? 'native.workspaceWord' : 'native.caseWord',
          detailKey: 'native.dialogClosed',
          detailText: '',
        });
      } else {
        setNotice({ kind: 'text', tone: 'info', titleKey: 'native.cancelUnavailable', titleWordKey: null, detailKey: null, detailText: result.reason });
      }
    } catch (error) {
      if (!lifecycle.isDisposed() && pending.contextGeneration === contextGenerationRef.current && pendingRequestRef.current?.handle === pending.handle) {
        setNotice({ kind: 'text', tone: 'error', titleKey: 'native.cancelFailed', titleWordKey: null, detailKey: null, detailText: error instanceof Error ? error.message : String(error) });
      }
    } finally {
      if (!lifecycle.isDisposed() && pending.contextGeneration === contextGenerationRef.current && pendingRequestRef.current?.handle === pending.handle) setCancelling(false);
    }
  }

  const noticeTitle = !notice
    ? ''
    : t(notice.titleKey, notice.kind === 'text' && notice.titleWordKey ? { what: t(notice.titleWordKey) } : undefined);
  const noticeDetail = !notice
    ? ''
    : notice.kind === 'selected'
      ? `${t(notice.count === 1 ? 'native.casesAvailableOne' : 'native.casesAvailableOther', { count: notice.count })}${notice.activeName ? t('native.activeCase', { name: notice.activeName }) : ''}`
      : notice.detailKey
        ? t(notice.detailKey)
        : notice.detailText;

  return (
    <div className={['native-context-surface', className].filter(Boolean).join(' ')}>
      <div className="native-context-actions" aria-label={t('native.actions')}>
        <Button variant="secondary" onClick={() => { void start('workspace'); }} disabled={pendingKind !== null}>{t('native.pickWorkspace')}</Button>
        <Button variant="secondary" onClick={() => { void start('case'); }} disabled={pendingKind !== null}>{t('native.openCase')}</Button>
      </div>
      {pendingKind && (
        <OperationStatus
          tone="busy"
          title={t(pendingKind === 'workspace' ? 'native.choosingWorkspace' : 'native.openingCase')}
          detail={t('native.completeDialog')}
          action={<Button variant="quiet" onClick={() => { void cancel(); }} busy={cancelling} busyLabel={t('native.cancelling')}>{t('native.cancel')}</Button>}
        />
      )}
      {!pendingKind && notice && <OperationStatus tone={notice.tone} title={noticeTitle} detail={noticeDetail} />}
    </div>
  );
}
