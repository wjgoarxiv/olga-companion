import { useEffect, useRef } from 'react';
import { scheduleIdleFocusReturn } from '../focusReturn';

export function Popover({
  open,
  onClose,
  label,
  children,
}: {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly label: string;
  readonly children: React.ReactNode;
}) {
  const box = useRef<HTMLDivElement | null>(null);

  const invoker = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (open) {
      invoker.current ??= document.activeElement as HTMLElement | null;
    } else if (invoker.current) {
      scheduleIdleFocusReturn(invoker.current);
      invoker.current = null;
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    box.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      ref={box}
      role="dialog"
      aria-label={label}
      tabIndex={-1}
      className="ui-popover"
    >
      {children}
    </div>
  );
}
