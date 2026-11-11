import { useEffect, useRef, useState } from 'react';
import { CircleGauge } from 'lucide-react';
import { useLocale } from './i18n/index.ts';
import type { I18nKey } from './i18n/index.ts';

import type { Capability, Health } from './types';

export const CAPABILITY_LABELS: Record<string, string> = {
  static_genkey: 'Static GENKEY',
  live_olga_run: 'Live OLGA Run',
  multiflash: 'Multiflash',
  result_analysis: 'Result Analysis',
  publication_export: 'Publication Export',
  opc_live_control: 'OPC Live Control',
  fluid_pvt_static: 'Fluid/PVT Static',
  solver_diagnostics: 'Solver Diagnostics'
};

export function capabilityRows(health: Health | null): readonly [string, Capability][] {
  if (!health) return [];
  return Object.entries(health.capabilities).filter(
    (entry): entry is [string, Capability] =>
      typeof entry[1] === 'object' && entry[1] !== null && 'enabled' in entry[1],
  );
}

export const CAPABILITY_LABEL_KEYS: Record<string, I18nKey> = {
  static_genkey: 'env.cap.staticGenkey',
  live_olga_run: 'env.cap.liveOlgaRun',
  multiflash: 'env.cap.multiflash',
  result_analysis: 'env.cap.resultAnalysis',
  publication_export: 'env.cap.publicationExport',
  opc_live_control: 'env.cap.opcLiveControl',
  fluid_pvt_static: 'env.cap.fluidPvtStatic',
  solver_diagnostics: 'env.cap.solverDiagnostics'
};

/** Diagnostics on demand — NOT a cryptic "N/M ready" count in the chrome. The
 *  connection dot is the only always-on signal (green = sidecar connected); click
 *  it to reveal the capability list. Available means the prerequisite was detected,
 *  not that an external runtime is healthy. Gated reads as a neutral designed state. */
export default function EnvDrawer({
  health,
  connected,
  runtimeLabel,
  modelLabel,
}: {
  health: Health | null;
  connected: boolean;
  runtimeLabel?: string;
  modelLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const { t } = useLocale();
  const menuRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const caps = capabilityRows(health);
  const resolvedRuntimeLabel = runtimeLabel ?? (connected ? t('env.sidecarOnline') ?? 'Sidecar online' : t('env.sidecarUnavailable') ?? 'Sidecar unavailable');

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(event: PointerEvent): void {
      if (event.target instanceof Node && !menuRef.current?.contains(event.target)) {
        setOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key !== 'Escape') return;
      setOpen(false);
      triggerRef.current?.focus();
    }
    document.addEventListener('pointerdown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  return (
    <div ref={menuRef} className="env-menu">
      <button
        ref={triggerRef}
        type="button"
        className={`conn ${connected ? 'ok' : 'off'}`}
        onClick={() => setOpen((v) => !v)}
        title={open ? t('env.closeTitle') : connected ? t('env.openTitleConnected') : t('env.openTitleOffline')}
        aria-label={open ? t('env.ariaClose', { runtime: resolvedRuntimeLabel, model: modelLabel }) : t('env.ariaOpen', { runtime: resolvedRuntimeLabel, model: modelLabel })}
        aria-expanded={open}
        aria-controls="runtime-diagnostics-panel"
      >
        <CircleGauge aria-hidden="true" focusable="false" strokeWidth={1.8} />
        <span className="conn-label">{t('env.systemStatus')}</span>
      </button>
      {open && (
        <div id="runtime-diagnostics-panel" className="env-popover">
          <p className="env-popover-head">{t('env.systemStatus')}</p>
          <p className="runtime-context">
            <span>{t('env.runtime')}</span>
            <strong>{resolvedRuntimeLabel}</strong>
          </p>
          <p className="runtime-context">
            <span>{t('env.aiModel')}</span>
            <strong>{modelLabel}</strong>
          </p>
          {!health && <p className="chrome-hint">{t('env.hint')}</p>}
          <ul className="capability-list">
            {caps.map(([name, cap]) => (
              <li key={name} className={cap.enabled ? 'capability enabled' : 'capability gated'}>
                <span>{(CAPABILITY_LABEL_KEYS[name] ? t(CAPABILITY_LABEL_KEYS[name]) : null) ?? CAPABILITY_LABELS[name] ?? name.replaceAll('_', ' ')}</span>
                <strong>{cap.enabled ? t('env.available') : t('env.gated')}</strong>
                <small>{cap.reason}</small>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
