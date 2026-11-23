import type { Profile } from './session';
import { labelWithName, type CaseNames } from './caseNames';
import { useLocale } from './i18n/index.ts';
import ErrorDetail from './ErrorDetail';
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
  readonly names?: CaseNames | null;
  readonly onBranchChange: (branch: string) => void;
  readonly onTimestepChange: (timestep: number) => void;
};

export function ProfileControls({
  branches, timesteps, branch, timestep, disabled, names, onBranchChange, onTimestepChange,
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
          {branches.map((name) => <option key={name} value={name}>{labelWithName(name, names)}</option>)}
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
  /** The server's code for a refused read: a headline in the app's language, with the raw text kept. */
  readonly errorCode?: string | null;
};

export default function ProfilePanel({ profile, loading, error, errorCode }: ProfilePanelProps) {
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
  if (error) return <OperationStatus tone="error" title={t('profile.unavailable')} detail={errorCode ? <ErrorDetail code={errorCode} text={error} /> : error} />;
  if (profile) return <ProfileChart profile={profile} />;
  return (
    <p className="ws-empty">
      {t('profile.pickHint')}
    </p>
  );
}
