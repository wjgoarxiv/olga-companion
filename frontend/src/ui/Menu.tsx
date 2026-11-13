import { useEffect, useRef, useState } from 'react';
import { scheduleIdleFocusReturn } from '../focusReturn';
import { moveRovingIndex } from './primitiveUtils';

export interface MenuEntry {
  readonly id: string;
  readonly label: string;
  readonly disabled?: boolean;
}

export function Menu({
  open,
  onClose,
  label,
  items,
  activeId,
  onSelect,
}: {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly label: string;
  readonly items: readonly MenuEntry[];
  readonly activeId?: string;
  readonly onSelect: (id: string) => void;
}) {
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);
  const start = Math.max(0, items.findIndex((item) => item.id === activeId));
  const [focus, setFocus] = useState(start);

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
    if (open) {
      setFocus(Math.max(0, items.findIndex((item) => item.id === activeId)));
      buttons.current[Math.max(0, items.findIndex((item) => item.id === activeId))]?.focus();
    }
  }, [open, items, activeId]);

  if (!open) return null;
  return (
    <div role="menu" aria-label={label} className="ui-menu">
      {items.map((item, index) => (
        <button
          key={item.id}
          ref={(node) => {
            buttons.current[index] = node;
          }}
          type="button"
          role="menuitem"
          tabIndex={index === focus ? 0 : -1}
          disabled={item.disabled}
          aria-disabled={item.disabled || undefined}
          className="ui-menuitem"
          onClick={() => {
            if (!item.disabled) {
              onSelect(item.id);
              onClose();
            }
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              onClose();
              return;
            }
            if (event.key !== 'Tab') event.preventDefault();
            const next = moveRovingIndex(index, items.length, event.key, 'vertical');
            if (next !== index) {
              setFocus(next);
              buttons.current[next]?.focus();
            }
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
