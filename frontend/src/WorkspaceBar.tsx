import { useEffect, useRef, useState } from 'react';
import { useLocale } from './i18n/index.ts';
import type { TranslateFn } from './i18n/index.ts';
import NativeContextActions from './NativeContextActions';
import type { WorkspaceCase } from './session';
import { workspaceRootLabel } from './workspaceLabels';

function pathFreeFilename(value: string | null): string | null {
  if (!value) return null;
  const parts = value.split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] ?? null;
}

function filenameParts(filename: string | null, t: TranslateFn): { readonly stem: string; readonly extension: string } {
  if (!filename) return { stem: t('workspace.noCase') ?? 'No case', extension: '' };
  const suffixIndex = filename.lastIndexOf('.');
  return suffixIndex > 0
    ? { stem: filename.slice(0, suffixIndex), extension: filename.slice(suffixIndex) }
    : { stem: filename, extension: '' };
}

/** The active-case chip opens a bounded case list and native context actions.
 *  Filesystem selection stays in the operating-system dialog. */
export default function WorkspaceBar({
  activeName: activeNameValue,
  cases,
  root,
  contextGeneration,
  onPick,
  onContextSelected,
}: {
  activeName: string | null;
  cases: WorkspaceCase[];
  root: string;
  contextGeneration: number;
  onPick: (rel: string) => void;
  onContextSelected: React.ComponentProps<typeof NativeContextActions>['onSelected'];
}) {
  const [open, setOpen] = useState(false);
  const { t } = useLocale();
  const menuRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  const activeName = pathFreeFilename(activeNameValue);
  const filename = filenameParts(activeName, t);
  const rootLabel = workspaceRootLabel(root);

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(event: PointerEvent): void {
      if (event.target instanceof Node && !menuRef.current?.contains(event.target)) {
        setOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key !== 'Escape') return;
      setOpen(false);
      triggerRef.current?.focus();
    }
    document.addEventListener('pointerdown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  function closeAndRestoreFocus(): void {
    setOpen(false);
    requestAnimationFrame(() => triggerRef.current?.focus());
  }

  return (
    <div ref={menuRef} className="workspace-bar">
      <button
        ref={triggerRef}
        type="button"
        className={`case-chip${activeName ? '' : ' empty'}`}
        onClick={() => setOpen((v) => !v)}
        aria-label={activeName ? `Active case: ${activeName}` : 'No active case — pick one'}
        aria-expanded={open}
        aria-controls="workspace-case-disclosure"
        title={activeName ? t('workspace.activeCaseTitle', { name: activeName }) ?? `Active case: ${activeName}` : t('workspace.noActiveCaseTitle') ?? 'No active case — pick one'}
      >
        <span className="case-dot" aria-hidden />
        <span className="case-context">
          <span className="case-context-label">{t('status.caseContext')}</span>
          <span className="case-name">
            <span className="case-name-stem">{filename.stem}</span>
            {filename.extension && <span className="case-name-extension">{filename.extension}</span>}
          </span>
        </span>
        <span className="case-disclosure-icon" aria-hidden>{open ? '−' : '+'}</span>
      </button>
      {open && (
        <div id="workspace-case-disclosure" className="workspace-popover">
          <p className="env-popover-head">{t('workspace.barHead') ?? 'Workspace'}</p>
          {cases.length === 0 && <p className="chrome-hint">{t('workspace.emptyChrome') ?? 'No .genkey / .tab files here yet.'}</p>}
          <ul className="case-list">
            {cases.map((c) => (
              <li key={c.rel}>
                <button
                  type="button"
                  className={`case-item${c.name === activeName ? ' current' : ''}`}
                  onClick={() => {
                    onPick(c.rel);
                    closeAndRestoreFocus();
                  }}
                >
                  <span className="case-item-name">{c.name}</span>
                  <span className="case-item-meta">{(c.size / 1024).toFixed(1)} KB</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="workspace-root-label">{t('workspace.rootLabel', { root: rootLabel }) ?? `Folder: ${rootLabel}`}</p>
          <NativeContextActions className="workspace-native-actions" contextGeneration={contextGeneration} onSelected={onContextSelected} />
        </div>
      )}
    </div>
  );
}
