import type { ProviderInfo } from './types';

type ProviderModel = ProviderInfo['models'][number];

export function normalizeModelEffort(model: ProviderModel | undefined, effort: string): string;
