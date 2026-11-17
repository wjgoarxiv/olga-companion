import { useSyncExternalStore } from 'react';
import { en } from './en.ts';
import { ko } from './ko.ts';
import type { I18nKey } from './ko.ts';

export type { I18nKey };
export type Locale = 'ko' | 'en';

export const DEFAULT_LOCALE: Locale = 'ko';
export const LOCALE_KEY = 'olga-companion.locale.v1';

type LocaleStorage = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
};

function browserStorage(): LocaleStorage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function parseLocale(value: unknown): Locale | null {
  return value === 'ko' || value === 'en' ? value : null;
}

export function loadLocale(storage: LocaleStorage | undefined = browserStorage()): Locale {
  try {
    const raw = storage?.getItem(LOCALE_KEY);
    if (raw === null || raw === undefined) return DEFAULT_LOCALE;
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed) || parsed['version'] !== 1) return DEFAULT_LOCALE;
    return parseLocale(parsed['locale']) ?? DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

export function saveLocale(locale: Locale, storage: LocaleStorage | undefined = browserStorage()): boolean {
  try {
    storage?.setItem(LOCALE_KEY, JSON.stringify({ version: 1, locale }));
    return storage !== undefined;
  } catch {
    return false;
  }
}

export type TranslateFn = (key: I18nKey | (string & {}), vars?: Record<string, string | number>) => string;

const LIFECYCLE_LABEL_KEYS: Record<string, I18nKey> = {
  'awaiting-approval': 'lifecycle.awaitingApproval',
  dispatched: 'lifecycle.dispatched',
  running: 'lifecycle.running',
  finalizing: 'lifecycle.finalizing',
  completed: 'lifecycle.completed',
  failed: 'lifecycle.failed',
  uncertain: 'lifecycle.uncertain',
  cancelled: 'lifecycle.cancelled',
};

export function lifecycleLabelKey(state: string): I18nKey {
  return LIFECYCLE_LABEL_KEYS[state] ?? 'lifecycle.uncertain';
}

export function translate(locale: string, key: I18nKey | (string & {}), vars?: Record<string, string | number>): string {
  const active: Record<string, string> = locale === 'en' ? en : ko;
  const template: string = active[key] ?? (ko as Record<string, string>)[key] ?? key;
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = vars[name];
    return value === undefined ? match : String(value);
  });
}

function applyDocumentLang(locale: Locale): void {
  try {
    if (typeof document !== 'undefined') document.documentElement.lang = locale;
  } catch {
    return;
  }
}

type Listener = () => void;

let current: Locale = loadLocale();
const listeners = new Set<Listener>();

applyDocumentLang(current);

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function snapshot(): Locale {
  return current;
}

export function currentLocale(): Locale {
  return current;
}

export function setLocale(next: Locale): void {
  if (next === current) return;
  current = next;
  saveLocale(next);
  applyDocumentLang(next);
  for (const listener of listeners) listener();
}

export function useLocale(): {
  locale: Locale;
  setLocale: (next: Locale) => void;
  t: TranslateFn;
} {
  const locale = useSyncExternalStore(subscribe, snapshot, () => DEFAULT_LOCALE);
  return { locale, setLocale, t: (key, vars) => translate(locale, key, vars) };
}
