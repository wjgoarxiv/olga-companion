import { useLocale } from '../i18n/index.ts';
import { previewCue } from '../sound.mjs';
import { Button } from './Button';

/** Volume slider and test button for the Settings sound row. The test sound
    plays only on the click; moving the slider is silent. */
export function SoundVolume({ volume, enabled, onVolume }: {
  readonly volume: number;
  readonly enabled: boolean;
  readonly onVolume: (next: number) => void;
}) {
  const { t } = useLocale();
  return (
    <>
      <span className="display-sound-range">
        <input
          id="display-sound-volume"
          type="range"
          min={0}
          max={100}
          step={5}
          value={volume}
          disabled={!enabled}
          aria-labelledby="display-sound-volume-label"
          onChange={(event) => onVolume(Number(event.target.value))}
        />
        <output className="display-sound-value" htmlFor="display-sound-volume">{volume}%</output>
      </span>
      <Button variant="secondary" disabled={!enabled} onClick={() => { previewCue(); }}>{t('settings.soundTest')}</Button>
    </>
  );
}
