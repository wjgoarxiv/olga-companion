import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type RefObject } from 'react';
import { useLocale } from './i18n/index.ts';
import { readLocalStorage, writeLocalStorage } from './safeLocalStorage';
import { formatSizeLabel } from './readoutFormat.mjs';
import { playCue } from './sound.mjs';
import { markUserResize, reclampPersistedWidths } from './shell/paneSpec.ts';

type PanelResizeHandleProps = {
  readonly targetRef: RefObject<HTMLElement | null>;
  readonly targetId: string;
  readonly label: string;
  readonly storageKey: string;
  readonly defaultWidth: number;
  readonly minWidth: number;
  readonly maxWidth: number;
  readonly className?: string;
  readonly direction?: 'grow-right' | 'grow-left';
};

const DIRECTION_SIGN = {
  'grow-right': 1,
  'grow-left': -1,
} as const satisfies Record<NonNullable<PanelResizeHandleProps['direction']>, 1 | -1>;

type DragState = {
  readonly pointerId: number;
  readonly startX: number;
  readonly startWidth: number;
};

function clampWidth(width: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, Math.round(width)));
}

function initialWidth(storageKey: string, fallback: number, minimum: number, maximum: number): number {
  // Load-time viewport re-clamp runs first (idempotent; mounts are loads
  // for these handles) so a stored width can never squeeze the centre.
  if (typeof window !== 'undefined') reclampPersistedWidths(window.innerWidth);
  const stored = Number(readLocalStorage(storageKey));
  return Number.isFinite(stored) && stored > 0 ? clampWidth(stored, minimum, maximum) : fallback;
}

export function PanelResizeHandle({
  targetRef,
  targetId,
  label,
  storageKey,
  defaultWidth,
  minWidth,
  maxWidth,
  className = '',
  direction = 'grow-right',
}: PanelResizeHandleProps) {
  const [width, setWidth] = useState(() => initialWidth(storageKey, defaultWidth, minWidth, maxWidth));
  const { t } = useLocale();
  const dragRef = useRef<DragState | null>(null);
  const directionSign = DIRECTION_SIGN[direction];

  useEffect(() => {
    targetRef.current?.style.setProperty('width', `${width}px`);
    writeLocalStorage(storageKey, String(width));
  }, [storageKey, targetRef, width]);

  function updateWidth(nextWidth: number): void {
    markUserResize(storageKey);
    setWidth(clampWidth(nextWidth, minWidth, maxWidth));
  }

  function handlePointerDown(event: PointerEvent<HTMLDivElement>): void {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startWidth: width };
    playCue('grab');
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>): void {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    updateWidth(drag.startWidth + (event.clientX - drag.startX) * directionSign);
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
    if (event.key === 'ArrowLeft') updateWidth(width - step * directionSign);
    else if (event.key === 'ArrowRight') updateWidth(width + step * directionSign);
    else if (event.key === 'Home') updateWidth(minWidth);
    else if (event.key === 'End') updateWidth(maxWidth);
    else return;
    event.preventDefault();
  }

  return (
    <div
      className={`panel-resizer ${className}`.trim()}
      role="separator"
      aria-label={label}
      aria-controls={targetId}
      aria-orientation="vertical"
      aria-valuemin={minWidth}
      aria-valuemax={maxWidth}
      aria-valuenow={width}
      aria-valuetext={t('resize.pixels', { width })}
      aria-keyshortcuts="ArrowLeft ArrowRight Home End"
      tabIndex={0}
      title={t('resize.hint')}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerEnd}
      onPointerCancel={handlePointerEnd}
      onDoubleClick={() => updateWidth(defaultWidth)}
      onKeyDown={handleKeyDown}
    >
      <span aria-hidden="true" />
      <i className="panel-resizer-label" aria-hidden="true">{formatSizeLabel('W', width)}</i>
    </div>
  );
}
