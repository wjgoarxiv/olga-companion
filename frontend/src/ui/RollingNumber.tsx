import { useEffect, useRef, useState } from 'react';
import { motionAllowsFull } from '../appearance';

/** Rolling inspector number: on value change the new reading slides up over
    the old one (Full motion only, Web Animations, transform/opacity). Reduced
    and Off swap instantly; without WAAPI support the final value renders. */
export function RollingNumber({ value, format }: { readonly value: number; readonly format: (n: number) => string }) {
  const [shown, setShown] = useState(value);
  const [incoming, setIncoming] = useState<number | null>(null);
  const stripRef = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    if (value === shown) return;
    if (!motionAllowsFull() || typeof stripRef.current?.animate !== 'function') {
      setShown(value);
      setIncoming(null);
      return;
    }
    setIncoming(value);
    const animation = stripRef.current?.animate(
      [{ transform: 'translateY(0)', opacity: 1 }, { transform: 'translateY(-1.2em)', opacity: 1 }],
      { duration: 160, easing: 'steps(3,end)' },
    );
    if (!animation) {
      setShown(value);
      setIncoming(null);
      return;
    }
    animation.onfinish = () => {
      setShown(value);
      setIncoming(null);
    };
    return () => animation.cancel();
  }, [value, shown]);

  return (
    <span className="ui-rolling" aria-live="off">
      <span className="ui-rolling-strip" ref={stripRef} aria-hidden={incoming !== null || undefined}>
        <span className="ui-rolling-current">{format(shown)}</span>
        {incoming !== null && <span className="ui-rolling-next">{format(incoming)}</span>}
      </span>
      <span className="ui-visually-hidden">{format(value)}</span>
    </span>
  );
}
