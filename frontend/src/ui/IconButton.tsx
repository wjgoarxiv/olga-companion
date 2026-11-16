export function IconButton({
  label,
  title,
  onClick,
  pressed,
  disabled,
  buttonRef,
  expanded,
  controls,
  toggleId,
  toggleClass,
  children,
  visibleLabel,
  keyshortcuts,
}: {
  readonly label: string;
  readonly title?: string;
  readonly onClick?: () => void;
  readonly pressed?: boolean;
  readonly disabled?: boolean;
  readonly buttonRef?: React.Ref<HTMLButtonElement>;
  readonly expanded?: boolean;
  readonly controls?: string;
  readonly toggleId?: string;
  readonly toggleClass?: string;
  readonly children: React.ReactNode;
  readonly visibleLabel?: string;
  readonly keyshortcuts?: string;
}) {
  return (
    <button
      ref={buttonRef}
      type="button"
      id={toggleId}
      aria-label={label}
      title={title ?? label}
      aria-pressed={pressed}
      aria-expanded={expanded}
      aria-controls={controls}
      aria-keyshortcuts={keyshortcuts}
      disabled={disabled}
      onClick={onClick}
      className={toggleClass ? `ui-iconbutton ${toggleClass}` : 'ui-iconbutton'}
    >
      <span aria-hidden="true" className="ui-iconbutton-glyph">{children}</span>
      {visibleLabel !== undefined && <span className="ui-iconbutton-label">{visibleLabel}</span>}
    </button>
  );
}
