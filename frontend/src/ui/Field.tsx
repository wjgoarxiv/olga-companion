import { cloneElement, isValidElement } from 'react';

export function Field({
  label,
  controlId,
  hint,
  error,
  children,
}: {
  readonly label: string;
  readonly controlId: string;
  readonly hint?: string;
  readonly error?: string;
  readonly children: React.ReactElement;
}) {
  const hintId = hint ? `${controlId}-hint` : undefined;
  const errorId = error ? `${controlId}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;
  const control = isValidElement(children)
    ? cloneElement(children, {
      id: controlId,
      ...(describedBy ? { 'aria-describedby': describedBy } : {}),
    } as Partial<unknown>)
    : children;

  return (
    <div className="ui-field">
      <label htmlFor={controlId} className="ui-field-label">{label}</label>
      {control}
      {hint && <p id={hintId} className="ui-field-hint">{hint}</p>}
      {error && <p id={errorId} role="alert" className="ui-field-error">{error}</p>}
    </div>
  );
}
