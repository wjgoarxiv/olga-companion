import { useEffect, useMemo, useRef, useState } from 'react';
import { scheduleIdleFocusReturn } from '../focusReturn';
import { filterPaletteItems } from './primitiveUtils';

export interface PaletteEntry {
  readonly id: string;
  readonly label: string;
  readonly hint?: string;
  readonly keywords?: string;
}

export function CommandPalette({
  open,
  onClose,
  label,
  placeholder,
  items,
  onSelect,
}: {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly label: string;
  readonly placeholder: string;
  readonly items: readonly PaletteEntry[];
  readonly onSelect: (id: string) => void;
}) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement | null>(null);
  const matches = useMemo(() => filterPaletteItems(items, query), [items, query]);

  const invoker = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (open) {
      invoker.current ??= document.activeElement as HTMLElement | null;
      setQuery('');
      setActive(0);
      input.current?.focus();
    } else if (invoker.current) {
      scheduleIdleFocusReturn(invoker.current);
      invoker.current = null;
    }
  }, [open]);

  useEffect(() => {
    setActive(0);
  }, [query]);

  if (!open) return null;
  const listId = 'ui-palette-list';
  return (
    <div className="ui-palette-overlay" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <div role="dialog" aria-label={label} aria-modal="true" className="ui-palette">
        <input
          ref={input}
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={matches.length > 0 ? `ui-palette-option-${matches[Math.min(active, matches.length - 1)].id}` : undefined}
          aria-autocomplete="list"
          aria-label={label}
          placeholder={placeholder}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              onClose();
            } else if (event.key === 'ArrowDown') {
              event.preventDefault();
              setActive((current) => (current + 1) % Math.max(1, matches.length));
            } else if (event.key === 'ArrowUp') {
              event.preventDefault();
              setActive((current) => (current - 1 + matches.length) % Math.max(1, matches.length));
            } else if (event.key === 'Enter') {
              const pick = matches[active];
              if (pick) {
                event.preventDefault();
                onSelect(pick.id);
                onClose();
              }
            }
          }}
          className="ui-palette-input"
        />
        <ul role="listbox" id={listId} aria-label={label} className="ui-palette-list">
          {matches.map((item, index) => (
            <li
              key={item.id}
              id={`ui-palette-option-${item.id}`}
              role="option"
              aria-selected={index === active}
              className="ui-palette-option"
              data-active={index === active || undefined}
              onMouseDown={(event) => {
                event.preventDefault();
                onSelect(item.id);
                onClose();
              }}
            >
              <span>{item.label}</span>
              {item.hint && <span className="ui-palette-hint">{item.hint}</span>}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
