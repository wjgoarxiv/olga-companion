import { useEffect, useState } from 'react';

type ActivityLoaderProps = {
  readonly loadingLabel: string;
  readonly className?: string;
  readonly detail?: string;
};

export function ActivityLoader({ loadingLabel, className, detail }: ActivityLoaderProps) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setVisible(true), 300);
    return () => window.clearTimeout(timer);
  }, []);
  if (!visible) return null;
  return (
    <div
      className={['activity-loader', className].filter(Boolean).join(' ')}
      role="status"
      aria-busy="true"
    >
      <i className="activity-loader-beacon" aria-hidden="true" />
      <i className="activity-loader-pixels" aria-hidden="true" />
      <span className="activity-loader-copy">
        <strong className="activity-loader-label">{loadingLabel}</strong>
        {detail && <span className="activity-loader-detail">{detail}</span>}
      </span>
    </div>
  );
}
