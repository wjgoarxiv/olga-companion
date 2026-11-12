import { useAppearance } from '../appearance';

export type Icon3DName =
  | 'approval' | 'error' | 'explorer' | 'export' | 'flowpath' | 'genkey'
  | 'node' | 'ppl' | 'pvt' | 'results' | 'riser' | 'run' | 'settings'
  | 'sink' | 'source' | 'success' | 'tab' | 'tpl' | 'validate' | 'valve' | 'warning';

/** 3D workbench icon. Picks the light/dark render for the active theme;
    decorative by default (aria-hidden), labelled when alt is given. */
export function Icon3D({
  name,
  size = 24,
  alt,
}: {
  readonly name: Icon3DName;
  readonly size?: number;
  readonly alt?: string;
}) {
  const { resolvedTheme } = useAppearance();
  const file = size <= 64 ? 64 : 96;
  return (
    <img
      src={`/icons/${resolvedTheme}/${name}-${file}.png`}
      width={size}
      height={size}
      alt={alt ?? ''}
      aria-hidden={alt === undefined || undefined}
      draggable={false}
      className="ui-icon3d"
    />
  );
}
