import { ActivityLoader } from './ActivityLoader';

type SkeletonProps = {
  readonly loadingLabel: string;
  readonly lines?: number;
  readonly visuallyHidden?: boolean;
  readonly className?: string;
};

export function Skeleton({ loadingLabel, lines = 3, visuallyHidden = false, className }: SkeletonProps) {
  return (
    <div className={['ui-skeleton', className].filter(Boolean).join(' ')}>
      <ActivityLoader className={visuallyHidden ? 'ui-visually-hidden' : undefined} loadingLabel={loadingLabel} />
      <span className="ui-skeleton-shape" aria-hidden="true">
        {Array.from({ length: Math.max(1, lines) }, (_, index) => <span key={index} />)}
      </span>
    </div>
  );
}
