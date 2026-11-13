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

function defaultActiveElement() {
  if (typeof document === 'undefined') return null;
  return document.activeElement === document.body ? null : document.activeElement;
}

export function scheduleIdleFocusReturn(target, schedule = defaultSchedule, getActive = defaultActiveElement) {
  return schedule(() => {
    const active = getActive();
    if (active && active.isConnected !== false) return;
    if (canRestoreFocus(target)) target.focus();
  });
}
