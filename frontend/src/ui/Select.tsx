export interface SelectOption {
  readonly value: string;
  readonly label: string;
  readonly disabled?: boolean;
}

export function Select({
  id,
  value,
  onChange,
  options,
  ariaLabel,
  describedBy,
}: {
  readonly id?: string;
  readonly value: string;
  readonly onChange: (next: string) => void;
  readonly options: readonly SelectOption[];
  readonly ariaLabel: string;
  readonly describedBy?: string;
}) {
  return (
    <select
      id={id}
      aria-label={ariaLabel}
      aria-describedby={describedBy}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="ui-select"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value} disabled={option.disabled}>{option.label}</option>
      ))}
    </select>
  );
}
