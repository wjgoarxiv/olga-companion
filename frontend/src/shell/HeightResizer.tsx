import { useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type RefObject } from 'react';
import { useLocale } from '../i18n/index.ts';
import { formatSizeLabel } from '../readoutFormat.mjs';
import { playCue } from '../sound.mjs';
import { readLocalStorage, writeLocalStorage } from '../safeLocalStorage';
import { markUserResize, reclampPersistedWidths } from './paneSpec.ts';

type HeightResizerProps = {
  readonly targetRef: RefObject<HTMLElement | null>;
  readonly targetId: string;
  readonly label: string;
  readonly storageKey: string;
  readonly defaultHeight: number;
  readonly minHeight: number;
  readonly maxHeight: number;
  readonly className?: string;
};

function clampHeight(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, Math.round(value)));
}

/** Stored-or-default height, shared so the panel can paint it declaratively
    before the resizer effect runs (the effect ref may lag on first mount). */
export function resolvePanelHeight(
  storageKey: string,
  defaultHeight: number,
  minHeight: number,
  maxHeight: number,
): number {
  // Same load-time re-clamp as the width handles (idempotent).
  if (typeof window !== 'undefined') reclampPersistedWidths(window.innerWidth);
  const stored = Number(readLocalStorage(storageKey));
  return Number.isFinite(stored) && stored > 0
    ? clampHeight(stored, minHeight, maxHeight)
    : defaultHeight;
}

/** Horizontal separator that resizes the panel above it. The shared width
    handle stays untouched; this covers the bottom-panel height case. */
export function HeightResizer({
  targetRef,
  targetId,
  label,
  storageKey,
  defaultHeight,
  minHeight,
  maxHeight,
  className = '',
}: HeightResizerProps) {
  const [height, setHeight] = useState(() =>
    resolvePanelHeight(storageKey, defaultHeight, minHeight, maxHeight),
  );
  const { t } = useLocale();
  const dragRef = useRef<{ readonly pointerId: number; readonly startY: number; readonly startHeight: number } | null>(null);

  // Layout effect (not passive effect): the stored-or-default height must land
  // on the panel before first paint, otherwise first paint sizes to content.
  useLayoutEffect(() => {
    targetRef.current?.style.setProperty('height', `${height}px`);
    writeLocalStorage(storageKey, String(height));
  }, [storageKey, targetRef, height]);

  function updateHeight(next: number): void {
    markUserResize(storageKey);
    setHeight(clampHeight(next, minHeight, maxHeight));
  }

  function handlePointerDown(event: PointerEvent<HTMLDivElement>): void {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { pointerId: event.pointerId, startY: event.clientY, startHeight: height };
    playCue('grab');
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>): void {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    updateHeight(drag.startHeight + (drag.startY - event.clientY));
  }

  function handlePointerEnd(event: PointerEvent<HTMLDivElement>): void {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    dragRef.current = null;
    playCue('release');
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    const step = event.shiftKey ? 32 : 12;
    if (event.key === 'ArrowUp') updateHeight(height + step);
    else if (event.key === 'ArrowDown') updateHeight(height - step);
    else if (event.key === 'Home') updateHeight(minHeight);
    else if (event.key === 'End') updateHeight(maxHeight);
    else return;
    event.preventDefault();
  }

  return (
    <div
      className={`panel-resizer is-horizontal ${className}`.trim()}
      role="separator"
      aria-label={label}
      aria-controls={targetId}
      aria-orientation="horizontal"
      aria-valuemin={minHeight}
      aria-valuemax={maxHeight}
      aria-valuenow={height}
      aria-valuetext={t('resize.pixels', { width: height })}
      aria-keyshortcuts="ArrowUp ArrowDown Home End"
      tabIndex={0}
      title={t('resize.hint')}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerEnd}
      onPointerCancel={handlePointerEnd}
      onDoubleClick={() => updateHeight(defaultHeight)}
      onKeyDown={handleKeyDown}
    >
      <span aria-hidden="true" />
      <i className="panel-resizer-label" aria-hidden="true">{formatSizeLabel('H', height)}</i>
    </div>
  );
}
