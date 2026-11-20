import { useCallback, useSyncExternalStore } from 'react';
import { readLocalStorage, writeLocalStorage } from './safeLocalStorage';
import { DEFAULT_SOUND_VOLUME, installSoundUnlock, parseSoundMode, parseSoundVolume, setSoundSettings, unlockSound } from './sound.mjs';

export type ThemeChoice = 'system' | 'light' | 'dark';
export type MotionChoice = 'system' | 'off' | 'subtle' | 'full';
export type DensityChoice = 'comfortable' | 'compact';
export type UiScaleChoice = 80 | 90 | 100 | 110 | 120 | 130;
export type SoundChoice = 'off' | 'quiet' | 'full';
export type ResolvedTheme = 'light' | 'dark';
export type ResolvedMotion = 'off' | 'subtle' | 'full';

export const THEME_KEY = 'olga-companion.theme.v1';
export const MOTION_KEY = 'olga-companion.motion.v1';
export const DENSITY_KEY = 'olga-companion.density.v1';
export const UI_SCALE_KEY = 'olga-companion.ui-scale.v1';
export const SOUND_KEY = 'olga-companion.sound.v1';
export const SOUND_VOLUME_KEY = 'olga-companion.sound-volume.v1';
export const SOUND_DEBUG_KEY = 'olga-companion.sound-debug.v1';

const THEMES: readonly ThemeChoice[] = ['system', 'light', 'dark'];
const MOTIONS: readonly MotionChoice[] = ['system', 'off', 'subtle', 'full'];
const DENSITIES: readonly DensityChoice[] = ['comfortable', 'compact'];
export const UI_SCALES: readonly UiScaleChoice[] = [80, 90, 100, 110, 120, 130];

export function parseTheme(value: unknown): ThemeChoice | null {
  return typeof value === 'string' && (THEMES as readonly string[]).includes(value)
    ? (value as ThemeChoice)
    : null;
}

export function parseMotion(value: unknown): MotionChoice | null {
  // A stored "reduced" (the earlier Full / Reduced / Off setting) reads as subtle.
  if (value === 'reduced') return 'subtle';
  return typeof value === 'string' && (MOTIONS as readonly string[]).includes(value)
    ? (value as MotionChoice)
    : null;
}

export function loadTheme(): ThemeChoice {
  return parseTheme(readLocalStorage(THEME_KEY)) ?? 'system';
}

export function loadMotion(): MotionChoice {
  return parseMotion(readLocalStorage(MOTION_KEY)) ?? 'system';
}

export function parseDensity(value: unknown): DensityChoice | null {
  return typeof value === 'string' && (DENSITIES as readonly string[]).includes(value)
    ? (value as DensityChoice)
    : null;
}

export function loadDensity(): DensityChoice {
  return parseDensity(readLocalStorage(DENSITY_KEY)) ?? 'compact';
}

export function parseSound(value: unknown): SoundChoice | null {
  return parseSoundMode(value);
}

export function loadSound(): SoundChoice {
  return parseSound(readLocalStorage(SOUND_KEY)) ?? 'off';
}

export function saveSound(choice: SoundChoice): void {
  writeLocalStorage(SOUND_KEY, choice);
}

export function loadSoundVolume(): number {
  return parseSoundVolume(readLocalStorage(SOUND_VOLUME_KEY)) ?? DEFAULT_SOUND_VOLUME;
}

export function saveSoundVolume(volume: number): void {
  writeLocalStorage(SOUND_VOLUME_KEY, String(Math.min(100, Math.max(0, Math.round(volume)))));
}

function applySoundSettings(): void {
  setSoundSettings({ mode: loadSound(), volume: loadSoundVolume() });
}

export function parseUiScale(value: unknown): UiScaleChoice | null {
  const step = typeof value === 'string' ? Number(value) : value;
  return (UI_SCALES as readonly unknown[]).includes(step) ? (step as UiScaleChoice) : null;
}

export function loadUiScale(): UiScaleChoice {
  return parseUiScale(readLocalStorage(UI_SCALE_KEY)) ?? 100;
}

export function saveUiScale(choice: UiScaleChoice): void {
  writeLocalStorage(UI_SCALE_KEY, String(choice));
}

export function applyUiScaleAttribute(choice: UiScaleChoice): void {
  try {
    document.documentElement.setAttribute('data-ui-scale', String(choice));
  } catch {
    return;
  }
}

export function saveDensity(choice: DensityChoice): void {
  writeLocalStorage(DENSITY_KEY, choice);
}

export function applyDensityAttribute(choice: DensityChoice): void {
  try {
    document.documentElement.setAttribute('data-density', choice);
  } catch {
    return;
  }
}

export function saveTheme(choice: ThemeChoice): void {
  writeLocalStorage(THEME_KEY, choice);
}

export function applyThemeChoice(choice: ThemeChoice): void {
  saveTheme(choice);
  applyThemeAttribute(resolveTheme(choice, prefersDark()));
}

export function saveMotion(choice: MotionChoice): void {
  writeLocalStorage(MOTION_KEY, choice);
}

function prefersDark(): boolean {
  try {
    return typeof window !== 'undefined'
      && typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-color-scheme: dark)').matches;
  } catch {
    return false;
  }
}

function prefersReducedMotion(): boolean {
  try {
    return typeof window !== 'undefined'
      && typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

export function resolveTheme(choice: ThemeChoice, systemDark: boolean): ResolvedTheme {
  if (choice === 'light') return 'light';
  if (choice === 'dark') return 'dark';
  return systemDark ? 'dark' : 'light';
}

export function resolveMotion(choice: MotionChoice, systemReduced: boolean): ResolvedMotion {
  if (choice === 'full') return 'full';
  if (choice === 'subtle') return 'subtle';
  if (choice === 'off') return 'off';
  return systemReduced ? 'off' : 'subtle';
}

export function applyThemeAttribute(resolved: ResolvedTheme): void {
  try {
    document.documentElement.setAttribute('data-theme', resolved);
  } catch {
    return;
  }
}

export function applyMotionAttribute(resolved: ResolvedMotion): void {
  try {
    document.documentElement.setAttribute('data-motion', resolved);
  } catch {
    return;
  }
}

// Setters bump a version so the hook re-renders its readers (the stored
// choices live in localStorage, which has no change event of its own).
let appearanceVersion = 0;
const appearanceListeners = new Set<() => void>();

function announceAppearance(): void {
  appearanceVersion += 1;
  appearanceListeners.forEach((listener) => listener());
}

function subscribeVisible(callback: () => void): () => void {
  appearanceListeners.add(callback);
  const unsubscribe = subscribeMedia(callback);
  return () => {
    appearanceListeners.delete(callback);
    unsubscribe();
  };
}

function subscribeMedia(callback: () => void): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return () => undefined;
  }
  const dark = window.matchMedia('(prefers-color-scheme: dark)');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const handler = () => callback();
  try {
    dark.addEventListener('change', handler);
    reduced.addEventListener('change', handler);
  } catch {
    return () => undefined;
  }
  return () => {
    try {
      dark.removeEventListener('change', handler);
      reduced.removeEventListener('change', handler);
    } catch {
      return;
    }
  };
}

function snapshotVisible(): number {
  return appearanceVersion * 4 + Number(prefersDark()) * 2 + Number(prefersReducedMotion());
}

export function motionAllowsFull(): boolean {
  return resolveMotion(loadMotion(), prefersReducedMotion()) === 'full';
}

/** Paint-safe startup: resolve stored choices against the OS and stamp the
    attributes before the first frame. */
export function initAppearance(): void {
  applyThemeAttribute(resolveTheme(loadTheme(), prefersDark()));
  applyMotionAttribute(resolveMotion(loadMotion(), prefersReducedMotion()));
  applyDensityAttribute(loadDensity());
  applyUiScaleAttribute(loadUiScale());
  applySoundSettings();
  installSoundUnlock({ debug: readLocalStorage(SOUND_DEBUG_KEY) === '1' });
}

export function useAppearance(): {
  theme: ThemeChoice;
  motion: MotionChoice;
  density: DensityChoice;
  uiScale: UiScaleChoice;
  sound: SoundChoice;
  soundVolume: number;
  resolvedTheme: ResolvedTheme;
  resolvedMotion: ResolvedMotion;
  setTheme: (next: ThemeChoice) => void;
  setMotion: (next: MotionChoice) => void;
  setDensity: (next: DensityChoice) => void;
  setUiScale: (next: UiScaleChoice) => void;
  setSound: (next: SoundChoice) => void;
  setSoundVolume: (next: number) => void;
} {
  useSyncExternalStore(subscribeVisible, snapshotVisible, () => 0);
  const theme = loadTheme();
  const motion = loadMotion();
  const density = loadDensity();
  const uiScale = loadUiScale();
  const sound = loadSound();
  const soundVolume = loadSoundVolume();
  const resolvedTheme = resolveTheme(theme, prefersDark());
  const resolvedMotion = resolveMotion(motion, prefersReducedMotion());
  const setTheme = useCallback((next: ThemeChoice) => {
    applyThemeChoice(next);
    announceAppearance();
  }, []);
  const setMotion = useCallback((next: MotionChoice) => {
    saveMotion(next);
    applyMotionAttribute(resolveMotion(next, prefersReducedMotion()));
    announceAppearance();
  }, []);
  const setDensity = useCallback((next: DensityChoice) => {
    saveDensity(next);
    applyDensityAttribute(next);
    announceAppearance();
  }, []);
  const setUiScale = useCallback((next: UiScaleChoice) => {
    saveUiScale(next);
    applyUiScaleAttribute(next);
    announceAppearance();
  }, []);
  const setSound = useCallback((next: SoundChoice) => {
    saveSound(next);
    applySoundSettings();
    unlockSound();
    announceAppearance();
  }, []);
  const setSoundVolume = useCallback((next: number) => {
    saveSoundVolume(next);
    applySoundSettings();
    announceAppearance();
  }, []);
  return { theme, motion, density, uiScale, sound, soundVolume, resolvedTheme, resolvedMotion, setTheme, setMotion, setDensity, setUiScale, setSound, setSoundVolume };
}
