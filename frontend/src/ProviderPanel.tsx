import { useEffect } from 'react';
import { translate, useLocale, type Locale } from './i18n/index.ts';
import { normalizeModelEffort } from './modelEffort';
import type { ProviderInfo } from './types';
import { Field } from './ui/Field';
import { Select } from './ui/Select';

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI (Codex)',
  copilot: 'GitHub Copilot',
  antigravity: 'Antigravity (Gemini)',
  xai: 'xAI (Grok)',
  anthropic: 'Anthropic',
  openrouter: 'OpenRouter',
  apikey: 'API 키'
};

export function providerDisplayLabel(providerId: string, locale: Locale = 'ko'): string {
  if (providerId === 'apikey') return translate(locale, 'provider.apikeyName');
  return PROVIDER_LABELS[providerId] ?? providerId;
}

export function providerConnected(provider: ProviderInfo): boolean {
  return provider.connected ?? provider.has_catalog;
}

const KOREAN_PARENTHETICAL = /\s*\([^)]*[\u3131-\uD79D][^)]*\)/g;

const EFFORT_LABELS: Readonly<Record<string, string>> = {
  max: 'max',
  xhigh: 'xhigh',
  high: 'high',
  medium: 'medium',
  low: 'low'
};

type EffortOption = {
  readonly value: string;
  readonly label: string;
};

const effortOption = (value: string): EffortOption => ({
  value,
  label: operatorEffortLabel(value)
});

export function operatorModelLabel(model: ProviderInfo['models'][number]): string {
  const source = model.label?.trim() || model.id;
  const normalized = source.replace(KOREAN_PARENTHETICAL, '').trim();
  return normalized || model.id;
}

export function operatorEffortLabel(effort: string): string {
  return EFFORT_LABELS[effort] ?? effort;
}

export default function ProviderPanel({
  providers,
  provider,
  model,
  effort,
  onProvider,
  onModel,
  onEffort
}: {
  providers: ProviderInfo[];
  provider: string;
  model: string;
  effort: string;
  onProvider: (p: string) => void;
  onModel: (m: string) => void;
  onEffort: (e: string) => void;
}) {
  const active = providers.find((p) => p.provider === provider);
  const activeConnected = active ? providerConnected(active) : false;
  const activeModels = activeConnected ? active?.models ?? [] : [];
  const hasModels = activeModels.length > 0;
  const supportsEffort = provider === 'openai' && activeConnected;
  const { locale, t } = useLocale();
  const activeModel = activeModels.find((candidate) => candidate.id === model);
  const effortOptions = (activeModel?.reasoning_efforts ?? []).map(effortOption);
  const modelLabel = provider === 'apikey' ? t('provider.connection') : t('provider.model');

  useEffect(() => {
    if (!supportsEffort || !activeModel) return;
    const normalized = normalizeModelEffort(activeModel, effort);
    if (normalized !== effort) onEffort(normalized);
  }, [activeModel, effort, onEffort, supportsEffort]);

  function changeProvider(nextProviderId: string) {
    const nextProvider = providers.find((candidate) => candidate.provider === nextProviderId);
    const nextModel = nextProvider && providerConnected(nextProvider) ? nextProvider.models[0] : undefined;
    onProvider(nextProviderId);
    if (!nextModel) return;
    onModel(nextModel.id);
    const normalized = normalizeModelEffort(nextModel, effort);
    if (normalized !== effort) onEffort(normalized);
  }

  function changeModel(nextModelId: string) {
    const nextModel = activeModels.find((candidate) => candidate.id === nextModelId);
    onModel(nextModelId);
    const normalized = normalizeModelEffort(nextModel, effort);
    if (normalized !== effort) onEffort(normalized);
  }

  const providerOptions = providers.map((p) => {
    const connected = providerConnected(p);
    const selected = p.provider === provider;
    return {
      value: p.provider,
      label: `${providerDisplayLabel(p.provider, locale)}${connected ? '' : t('provider.notConnectedSuffix')}`,
      disabled: !connected && !selected,
    };
  });
  const modelOptions = activeModels.map((m) => ({ value: m.id, label: operatorModelLabel(m) }));
  const effortSelectOptions = effortOptions.map((o) => ({ value: o.value, label: o.label }));

  return (
    <div className="provider-control" aria-label={t('settings.providerTitle')}>
      <Field label={t('provider.provider')} controlId="provider-select">
        <Select ariaLabel={t('provider.provider')} value={provider} onChange={changeProvider} options={providerOptions} />
      </Field>
      {active && !activeConnected ? (
        <p className="provider-notice" role="status">{t('provider.disconnectedNotice')}</p>
      ) : (
        hasModels && (
          <Field label={modelLabel} controlId="provider-model-select">
            <Select ariaLabel={modelLabel} value={model} onChange={changeModel} options={modelOptions} />
          </Field>
        )
      )}
      {supportsEffort && activeModel && (
        <Field label={t('provider.effort')} controlId="provider-effort-select" hint={t('provider.effortTitle') ?? 'Reasoning effort — deeper ↔ faster'}>
          <Select ariaLabel={t('provider.effort')} value={effort} onChange={onEffort} options={effortSelectOptions} />
        </Field>
      )}
    </div>
  );
}
