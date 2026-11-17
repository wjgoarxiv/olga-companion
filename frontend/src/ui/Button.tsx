import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'quiet';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  readonly variant?: ButtonVariant;
  readonly busy?: boolean;
  readonly busyLabel?: string;
  readonly icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button({
    variant = 'secondary',
    busy = false,
    busyLabel,
    icon,
    children,
    className,
    disabled,
    type = 'button',
    ...props
  }, ref) {
  return (
    <button
      {...props}
      ref={ref}
      type={type}
      className={['ui-button', `ui-button-${variant}`, className].filter(Boolean).join(' ')}
      aria-busy={busy || undefined}
      data-busy={busy || undefined}
      disabled={disabled || busy}
    >
      {icon && <span className="ui-button-icon" aria-hidden="true">{icon}</span>}
      <span className="ui-button-label">
        <span aria-live="polite">{busy ? busyLabel ?? children : children}</span>
        {busy && busyLabel && <span className="ui-button-label-measure" aria-hidden="true">{children}</span>}
      </span>
    </button>
  );
});
