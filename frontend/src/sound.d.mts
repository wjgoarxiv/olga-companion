export type SoundMode = 'off' | 'quiet' | 'full';
export type SoundCue = 'tick' | 'grab' | 'release' | 'pass' | 'fail' | 'runDone' | 'runFail' | 'done' | 'error';

export interface SoundCueDefinition {
  readonly tier: 'quiet' | 'full';
  readonly steps: readonly {
    readonly v: 'osc' | 'noise';
    readonly wave?: string;
    readonly f?: readonly [number, number];
    readonly hp?: number;
    readonly at: number;
    readonly ms: number;
    readonly g: number;
    readonly crush?: boolean;
  }[];
}

export interface SoundSettings {
  readonly mode: SoundMode;
  readonly volume: number;
}

export interface SoundEngine {
  configure(next: Partial<SoundSettings>): void;
  unlock(): void;
  play(cue: SoundCue): boolean;
  preview(): boolean;
  trackRun(runId: string): void;
  playRunOutcome(runId: string, state: string): boolean;
  masterGain(): number;
  settings(): SoundSettings;
  audioState(): string;
  log(): { readonly cue: SoundCue; readonly at: number }[];
}

export const SOUND_MODES: readonly SoundMode[];
export const CUES: Readonly<Record<SoundCue, SoundCueDefinition>>;
export const DEFAULT_SOUND_VOLUME: number;
export function parseSoundMode(value: unknown): SoundMode | null;
export function parseSoundVolume(value: unknown): number | null;
export function cueAllowed(mode: SoundMode, cue: string): boolean;
export function cueDurationMs(cue: string): number;
export function createSound(options?: {
  AudioContext?: unknown;
  isHidden?: () => boolean;
  now?: () => number;
}): SoundEngine;
export function setSoundSettings(next: Partial<SoundSettings>): void;
export function unlockSound(): void;
export function playCue(cue: SoundCue): boolean;
export function previewCue(): boolean;
export function trackRun(runId: string): void;
export function cueRunOutcome(runId: string, state: string): boolean;
export function installSoundUnlock(options?: { debug?: boolean }): void;
