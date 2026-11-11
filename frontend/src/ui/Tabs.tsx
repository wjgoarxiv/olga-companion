import { useRef } from 'react';
import { moveRovingIndex } from './primitiveUtils';

export interface TabItem {
  readonly id: string;
  readonly label: string;
  readonly badge?: string;
}

export function Tabs({
  items,
  value,
  onChange,
  ariaLabel,
  children,
}: {
  readonly items: readonly TabItem[];
  readonly value: string;
  readonly onChange: (next: string) => void;
  readonly ariaLabel: string;
  readonly children: React.ReactNode;
}) {
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);
  const selected = Math.max(0, items.findIndex((item) => item.id === value));

  return (
    <div className="ui-tabs">
      <div role="tablist" aria-label={ariaLabel} className="ui-tablist">
        {items.map((item, index) => {
          const active = item.id === value;
          return (
            <button
              key={item.id}
              ref={(node) => {
                tabs.current[index] = node;
              }}
              type="button"
              role="tab"
              id={`ui-tab-${item.id}`}
              aria-selected={active}
              aria-controls={`ui-tabpanel-${item.id}`}
              tabIndex={index === selected ? 0 : -1}
              className="ui-tab"
              onClick={() => onChange(item.id)}
              onKeyDown={(event) => {
                const next = moveRovingIndex(index, items.length, event.key);
                if (next !== index) {
                  event.preventDefault();
                  onChange(items[next].id);
                  tabs.current[next]?.focus();
                }
              }}
            >
              {item.label}
              {item.badge !== undefined && item.badge !== '' && (
                <span key={item.badge} className="ui-tab-badge tick" aria-hidden="true">{item.badge}</span>
              )}
            </button>
          );
        })}
      </div>
      <div
        role="tabpanel"
        id={`ui-tabpanel-${value}`}
        aria-labelledby={`ui-tab-${value}`}
        tabIndex={0}
        className="ui-tabpanel"
      >
        {children}
      </div>
    </div>
  );
}
