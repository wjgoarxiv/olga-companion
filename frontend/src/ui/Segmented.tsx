import { useRef } from 'react';
import { moveRovingIndex } from './primitiveUtils';

export interface SegmentedOption<T extends string> {
  readonly value: T;
  readonly label: string;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  readonly options: readonly SegmentedOption<T>[];
  readonly value: T;
  readonly onChange: (next: T) => void;
  readonly ariaLabel: string;
}) {
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);
  const selected = Math.max(0, options.findIndex((option) => option.value === value));

  return (
    <div role="radiogroup" aria-label={ariaLabel} className="ui-segmented">
      {options.map((option, index) => {
        const checked = option.value === value;
        return (
          <button
            key={option.value}
            ref={(node) => {
              buttons.current[index] = node;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={index === selected ? 0 : -1}
            className="ui-segmented-option"
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => {
              const next = moveRovingIndex(index, options.length, event.key);
              if (next !== index) {
                event.preventDefault();
                onChange(options[next].value);
                buttons.current[next]?.focus();
              }
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
