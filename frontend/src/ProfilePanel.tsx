import type { Profile } from './session';
import { useLocale } from './i18n/index.ts';
import ProfileChart from './ProfileChart';
import { OperationStatus } from './ui/OperationStatus';
import { Skeleton } from './ui/Skeleton';

/* Everything a .ppl result needs to be reviewed spatially: which branch, which
 * profile time, and the resulting distribution along that branch. */

type ProfileControlsProps = {
  readonly branches: readonly string[];
  readonly timesteps: readonly number[];
  readonly branch: string | null;
  readonly timestep: number | null;
  readonly disabled: boolean;
  readonly onBranchChange: (branch: string) => void;
  readonly onTimestepChange: (timestep: number) => void;
};

export function ProfileControls({
  branches, timesteps, branch, timestep, disabled, onBranchChange, onTimestepChange,
}: ProfileControlsProps) {
  const { t } = useLocale();
  return (
    <div className="rv-profile-controls">
      <label>
        <span>{t('profile.branch')}</span>
        <select
          value={branch ?? ''}
          disabled={branches.length === 0 || disabled}
          onChange={(event) => { onBranchChange(event.target.value); }}
        >
          {branches.map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
      </label>
      <label>
        <span>{t('profile.time')}</span>
        <select
          value={timestep ?? ''}
          disabled={timesteps.length === 0 || disabled}
          onChange={(event) => { onTimestepChange(Number(event.target.value)); }}
        >
          {timesteps.map((value) => <option key={value} value={value}>{t('run.simSeconds', { seconds: value }) ?? `${value} s`}</option>)}
        </select>
      </label>
    </div>
  );
}

type ProfilePanelProps = {
  readonly profile: Profile | null;
  readonly loading: boolean;
  readonly error: string;
};

export default function ProfilePanel({ profile, loading, error }: ProfilePanelProps) {
  const { t } = useLocale();
  if (loading) {
    return (
      <Skeleton
        className="rv-loading"
        loadingLabel={t('profile.loading')}
        lines={4}
        visuallyHidden={false}
      />
    );
  }
  if (error) return <OperationStatus tone="error" title={t('profile.unavailable')} detail={error} />;
  if (profile) return <ProfileChart profile={profile} />;
  return (
    <p className="ws-empty">
      {t('profile.pickHint')}
    </p>
  );
}
