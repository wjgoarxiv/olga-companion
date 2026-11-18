import { useEffect, useRef, useState } from 'react';
import { loadProviderSelection, saveProviderSelection } from './providerSelectionApi';
import type { ProviderInfo } from './types';

export function useProviderSelection() {
  const [provider, setProvider] = useState('openai');
  const [model, setModel] = useState('');
  const [effort, setEffort] = useState('medium');
  const [online, setOnline] = useState(false);
  const [selectionReady, setSelectionReady] = useState(false);
  const selectionReadyRef = useRef(false);

  function applyRuntimeProviders(next: ProviderInfo[]) {
    const firstConnected = next.find((candidate) => candidate.has_catalog);
    setProvider((currentProvider) => {
      const current = next.find((candidate) => candidate.provider === currentProvider);
      const keepSaved = selectionReadyRef.current && current != null;
      const selected = current && (current.has_catalog || keepSaved) ? current : firstConnected;
      if (!selected) return currentProvider;
      setModel((currentModel) => (
        selected.models.some((candidate) => candidate.id === currentModel)
          ? currentModel
          : selected.models[0]?.id ?? currentModel
      ));
      return selected.provider;
    });
  }

  useEffect(() => {
    if (!online) return;
    let cancelled = false;
    void loadProviderSelection()
      .then((saved) => {
        if (cancelled) return;
        if (saved) {
          setProvider(saved.provider);
          setModel(saved.model);
          setEffort(saved.variant || 'medium');
        }
        selectionReadyRef.current = true;
        setSelectionReady(true);
      })
      .catch(() => {
        if (cancelled) return;
        selectionReadyRef.current = true;
        setSelectionReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [online]);

  useEffect(() => {
    if (!selectionReady || !provider || !model) return;
    void saveProviderSelection({ provider, model, variant: effort }).catch(() => undefined);
  }, [selectionReady, provider, model, effort]);

  return {
    provider,
    setProvider,
    model,
    setModel,
    effort,
    setEffort,
    setOnline,
    applyRuntimeProviders,
  };
}
