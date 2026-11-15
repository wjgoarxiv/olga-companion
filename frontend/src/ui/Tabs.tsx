import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
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
  const list = useRef<HTMLDivElement | null>(null);
  // Sliding indicator: measured from the selected tab, moved with transform
  // only. Hidden from assistive tech; the border + aria-selected stay the
  // state signal, so a missed measurement never loses the selection.
  const [indicator, setIndicator] = useState<{ x: number; w: number } | null>(null);
  useLayoutEffect(() => {
    const update = () => {
      const bar = list.current;
      const active = tabs.current[selected];
      if (!bar || !active) {
        setIndicator((prev) => (prev === null ? prev : null));
        return;
      }
      const x = active.offsetLeft - bar.clientLeft;
      const w = active.offsetWidth;
      setIndicator((prev) => (prev && prev.x === x && prev.w === w ? prev : { x, w }));
    };
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, [selected, items]);

  return (
    <div className="ui-tabs">
      <div role="tablist" aria-label={ariaLabel} className="ui-tablist" ref={list}>
        {indicator && (
          <span
            className="ui-tab-indicator"
            aria-hidden="true"
            style={{ '--ind-x': `${indicator.x}px`, '--ind-w': indicator.w } as CSSProperties}
          />
        )}
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
