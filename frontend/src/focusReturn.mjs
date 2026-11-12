function defaultSchedule(callback) {
  if (typeof requestAnimationFrame === 'function') {
    const frame = requestAnimationFrame(callback);
    return () => cancelAnimationFrame(frame);
  }
  const timer = setTimeout(callback, 0);
  return () => clearTimeout(timer);
}

function canRestoreFocus(target) {
  return Boolean(
    target
    && target.isConnected
    && typeof target.focus === 'function'
    && !(typeof target.matches === 'function' && target.matches(':disabled, [aria-disabled="true"]'))
  );
}

export function scheduleFocusReturn(target, schedule = defaultSchedule, fallback) {
  return schedule(() => {
    const focusTarget = canRestoreFocus(target) ? target : fallback?.();
    if (canRestoreFocus(focusTarget)) focusTarget.focus();
  });
}
