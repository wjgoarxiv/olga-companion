import { useCallback, useEffect, useRef, useState } from 'react';
import NativeContextActions from './NativeContextActions';
import ProviderPanel, { providerConnected, providerDisplayLabel } from './ProviderPanel';
import ProxyPanel from './ProxyPanel';
import DiagnosticsPanel from './DiagnosticsPanel';
import UpdatePanel from './UpdatePanel';
import { subscribeOpenUpdates } from './updateAutoCheck.mjs';
import type { NativeSelectedContext } from './session';
import { workspaceRootLabel, workspaceRootTitle } from './workspaceLabels';
import type { ProviderInfo } from './types';
import { parseSignificantFigures, SIGNIFICANT_FIGURE_OPTIONS } from './significantFigures.mjs';
import { parseLocale, useLocale, type I18nKey, type Locale } from './i18n/index.ts';
import { setSignificantFigures, useSignificantFigures } from './useSignificantFigures';
import { fetchProviders } from './sessionTransport';
import XaiConnect from './XaiConnectPanel';
import ApiKeyConnections from './ApiKeyConnections';
import { Segmented } from './ui/Segmented';
import { UI_SCALES, useAppearance, type DensityChoice, type MotionChoice, type SoundChoice, type ThemeChoice, type UiScaleChoice } from './appearance';
import { SoundVolume } from './ui/SoundVolume';

type SettingsSection = 'general' | 'provider' | 'apikey' | 'workspace' | 'network' | 'updates' | 'support';

const SECTIONS: readonly { readonly id: SettingsSection; readonly labelKey: I18nKey }[] = [
  { id: 'general', labelKey: 'settings.sectionGeneral' },
  { id: 'provider', labelKey: 'settings.sectionProvider' },
  { id: 'apikey', labelKey: 'settings.sectionApikey' },
  { id: 'workspace', labelKey: 'settings.sectionWorkspace' },
  { id: 'network', labelKey: 'settings.sectionNetwork' },
  { id: 'updates', labelKey: 'settings.sectionUpdates' },
  { id: 'support', labelKey: 'settings.sectionSupport' },
];

/* The active section survives tab switches: SettingsView unmounts when the
   centre tab changes, so the choice lives outside render state. Session
   scope only — nothing is persisted to storage. */
let rememberedSection: SettingsSection | null = null;

export function rememberSettingsSection(section: SettingsSection) {
  rememberedSection = section;
}

function accountHint(provider: ProviderInfo, connected: boolean): I18nKey | null {
  if (connected) return null;
  if (provider.login === 'apikey' || provider.provider === 'apikey') {
    return 'settings.apikeyHint';
  }
  if (provider.login === 'xai_device' || provider.provider === 'xai') return null;
  return 'settings.externalHint';
}

const LANGUAGE_OPTIONS: readonly { readonly value: Locale; readonly labelKey: I18nKey }[] = [
  { value: 'ko', labelKey: 'language.korean' },
  { value: 'en', labelKey: 'language.english' },
];

const DENSITY_OPTIONS: readonly { readonly value: DensityChoice; readonly labelKey: I18nKey }[] = [
  { value: 'comfortable', labelKey: 'settings.densityComfortable' },
  { value: 'compact', labelKey: 'settings.densityCompact' },
];

export default function SettingsView({
  providers,
  provider,
  model,
  effort,
  onProvider,
  onModel,
  onEffort,
  workspaceRoot,
  contextGeneration,
  onContextSelected,
}: {
  providers: ProviderInfo[];
  provider: string;
  model: string;
  effort: string;
  onProvider: (p: string) => void;
  onModel: (m: string) => void;
  onEffort: (e: string) => void;
  workspaceRoot: string;
  contextGeneration: number;
  onContextSelected: (context: NativeSelectedContext) => void | Promise<void>;
}) {
  const currentRootLabel = workspaceRootLabel(workspaceRoot);
  const currentRootTitle = workspaceRootTitle(workspaceRoot);
  const { locale, setLocale, t } = useLocale();
  const significantFigures = useSignificantFigures();
  const appearance = useAppearance();
  const themeOptions: readonly { readonly value: ThemeChoice; readonly label: string }[] = [
    { value: 'system', label: t('settings.themeSystem') },
    { value: 'light', label: t('settings.themeLight') },
    { value: 'dark', label: t('settings.themeDark') },
  ];
  const motionOptions: readonly { readonly value: MotionChoice; readonly label: string }[] = [
    { value: 'system', label: t('settings.motionSystem') },
    { value: 'off', label: t('settings.motionOff') },
    { value: 'subtle', label: t('settings.motionSubtle') },
    { value: 'full', label: t('settings.motionFull') },
  ];
  const soundOptions: readonly { readonly value: SoundChoice; readonly label: string }[] = [
    { value: 'off', label: t('settings.soundOff') },
    { value: 'quiet', label: t('settings.soundQuiet') },
    { value: 'full', label: t('settings.soundFull') },
  ];
  const uiScaleOptions = UI_SCALES.map((step) => ({ value: String(step), label: `${step}%` }));
  const densityOptions = DENSITY_OPTIONS.map((option) => ({ value: option.value, label: t(option.labelKey) }));
  const [freshProviders, setFreshProviders] = useState<ProviderInfo[] | null>(null);
  const [section, setSection] = useState<SettingsSection>(rememberedSection ?? 'general');
  const sectionButtons = useRef<Array<HTMLButtonElement | null>>([]);
  useEffect(() => setFreshProviders(null), [providers]);
  const refreshProviders = useCallback(() => {
    fetchProviders().then(setFreshProviders).catch(() => undefined);
  }, []);
  const visibleProviders = freshProviders ?? providers;

  const selectSection = useCallback((next: SettingsSection, focus = false) => {
    rememberedSection = next;
    setSection(next);
    if (focus) {
      const index = SECTIONS.findIndex((entry) => entry.id === next);
      sectionButtons.current[index]?.focus();
    }
  }, []);
  useEffect(() => subscribeOpenUpdates(() => selectSection('updates')), [selectSection]);

  const onSectionsKeyDown = useCallback((event: React.KeyboardEvent) => {
    const current = SECTIONS.findIndex((entry) => entry.id === section);
    let next: number | null = null;
    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = (current + 1) % SECTIONS.length;
    else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = (current + SECTIONS.length - 1) % SECTIONS.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = SECTIONS.length - 1;
    if (next === null) return;
    event.preventDefault();
    selectSection(SECTIONS[next].id, true);
  }, [section, selectSection]);

  return (
    <section className="settings-view" aria-label={t('settings.title')}>
      <header className="settings-hero">
        <div>
          <h2 className="view-title">{t('settings.title')}</h2>
          <p className="settings-note">{t('settings.lede')}</p>
        </div>
      </header>

      <div className="settings-layout">
        <nav className="settings-sections" aria-label={t('settings.sectionsLabel')}>
          <ul onKeyDown={onSectionsKeyDown}>
            {SECTIONS.map((entry, index) => {
              const active = entry.id === section;
              return (
                <li key={entry.id}>
                  <button
                    type="button"
                    ref={(node) => {
                      sectionButtons.current[index] = node;
                    }}
                    aria-current={active ? 'page' : undefined}
                    tabIndex={active ? 0 : -1}
                    onClick={() => selectSection(entry.id)}
                  >
                    {t(entry.labelKey)}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="settings-section-panel">
          {section === 'general' && (
            <>
              <article className="settings-card language-card">
                <div>
                  <h3 className="settings-h">{t('language.title')}</h3>
                  <p id="language-description" className="settings-note">{t('language.note')}</p>
                </div>
                <div className="language-control">
                  <label htmlFor="ui-language"><span>{t('language.title')}</span></label>
                  <select
                    id="ui-language"
                    aria-describedby="language-description"
                    value={locale}
                    onChange={(event) => {
                      const next = parseLocale(event.target.value);
                      if (next !== null) setLocale(next);
                    }}
                  >
                    {LANGUAGE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{t(option.labelKey)}</option>)}
                  </select>
                </div>
              </article>

              <article className="settings-card numeric-display-card">
                <div>
                  <h3 className="settings-h">{t('settings.numericTitle')}</h3>
                  <p id="numeric-display-description" className="settings-note">{t('settings.numericNote')}</p>
                </div>
                <div className="numeric-display-control">
                  <label htmlFor="significant-figures"><span>{t('settings.significantFigures')}</span></label>
                  <select
                    id="significant-figures"
                    aria-describedby="numeric-display-description"
                    value={significantFigures}
                    onChange={(event) => {
                      const next = parseSignificantFigures(event.target.value);
                      if (next !== null) setSignificantFigures(next);
                    }}
                  >
                    {SIGNIFICANT_FIGURE_OPTIONS.map((option) => <option key={option} value={option}>{t('settings.digits', { count: option })}</option>)}
                  </select>
                </div>
              </article>

              <article className="settings-card display-card">
                <div>
                  <h3 className="settings-h">{t('settings.displayTitle')}</h3>
                  <p className="settings-note">{t('settings.displayNote')}</p>
                </div>
                <div className="display-control">
                  <span id="display-ui-scale-label" className="display-label">{t('settings.uiScale')}</span>
                  <Segmented ariaLabel={t('settings.uiScale')} options={uiScaleOptions} value={String(appearance.uiScale)} onChange={(next) => appearance.setUiScale(Number(next) as UiScaleChoice)} />
                </div>
                <div className="display-control">
                  <span id="display-theme-label" className="display-label">{t('settings.theme')}</span>
                  <Segmented ariaLabel={t('settings.theme')} options={themeOptions} value={appearance.theme} onChange={appearance.setTheme} />
                </div>
                <div className="display-control">
                  <span id="display-density-label" className="display-label">{t('settings.density')}</span>
                  <Segmented ariaLabel={t('settings.density')} options={densityOptions} value={appearance.density} onChange={appearance.setDensity} />
                </div>
                <div className="display-control">
                  <span id="display-motion-label" className="display-label">{t('settings.motion')}</span>
                  <Segmented ariaLabel={t('settings.motion')} options={motionOptions} value={appearance.motion} onChange={appearance.setMotion} />
                </div>
                <div className="display-control">
                  <span id="display-sound-label" className="display-label">{t('settings.sound')}</span>
                  <Segmented ariaLabel={t('settings.sound')} options={soundOptions} value={appearance.sound} onChange={appearance.setSound} />
                </div>
                <div className="display-control">
                  <span id="display-sound-volume-label" className="display-label">{t('settings.soundVolume')}</span>
                  <SoundVolume volume={appearance.soundVolume} enabled={appearance.sound !== 'off'} onVolume={appearance.setSoundVolume} />
                </div>
              </article>
            </>
          )}

          {section === 'provider' && (
            <article className="settings-card provider-card">
              <h3 className="settings-h">{t('settings.providerTitle')}</h3>
              <p className="settings-note">{t('settings.providerNote')}</p>
              <ProviderPanel providers={visibleProviders} provider={provider} model={model} effort={effort} onProvider={onProvider} onModel={onModel} onEffort={onEffort} />
              <hr className="provider-divider" />
              <div className="provider-accounts" aria-label={t('settings.accounts')}>
                <h4 className="provider-accounts-h">{t('settings.accounts')}</h4>
                <ul className="provider-account-list">
                  {visibleProviders.map((candidate) => {
                    const connected = providerConnected(candidate);
                    const hint = accountHint(candidate, connected);
                    const isXai = candidate.provider === 'xai';
                    return (
                      <li key={candidate.provider} className="provider-account-row" data-provider={candidate.provider}>
                        <div className="provider-account-head">
                          <strong>{providerDisplayLabel(candidate.provider, locale)}</strong>
                          <span className={connected ? 'provider-account-status is-connected' : 'provider-account-status'}>
                            {connected ? t('settings.connected') : t('settings.disconnected')}
                          </span>
                        </div>
                        {isXai && <XaiConnect onConnected={refreshProviders} />}
                        {hint && <p className="provider-account-hint">{t(hint)}</p>}
                      </li>
                    );
                  })}
                </ul>
              </div>
            </article>
          )}

          {section === 'apikey' && (
            <article className="settings-card apikey-card">
              <h3 className="settings-h">{t('settings.apikeyTitle')}</h3>
              <p className="settings-note">{t('settings.apikeyNote')}</p>
              <ApiKeyConnections onChanged={refreshProviders} />
            </article>
          )}

          {section === 'workspace' && (
            <article className="settings-card workspace-card">
              <h3 className="settings-h">{t('settings.workspaceTitle')}</h3>
              <p className="settings-note">{t('settings.workspaceNotePre')}<code>.genkey</code>·<code>.tab</code>·<code>.tpl</code>·<code>.ppl</code>{t('settings.workspaceNotePost')}</p>
              <div className="settings-current-row">
                <span>{t('settings.current')}</span>
                <p className="settings-current" title={currentRootTitle}>{currentRootLabel}</p>
              </div>
              <NativeContextActions contextGeneration={contextGeneration} onSelected={onContextSelected} />
            </article>
          )}

          {section === 'network' && <ProxyPanel />}

          {section === 'updates' && <UpdatePanel currentVersion={__APP_VERSION__} />}

          {section === 'support' && <DiagnosticsPanel />}
        </div>
      </div>
    </section>
  );
}
