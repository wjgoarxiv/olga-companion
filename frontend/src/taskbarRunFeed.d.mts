import type { TaskbarObservation } from './taskbarProgress.mjs';

export interface TaskbarSubject {
  readonly kind: 'run' | 'sweep';
  readonly id: string;
}

export function rememberTaskbarTarget(next: TaskbarSubject | null | undefined): boolean;
export function rememberTaskbarTargetIfAbsent(next: TaskbarSubject | null | undefined): boolean;
export function getTaskbarTarget(): TaskbarSubject | null;
export function clearTaskbarTargetIf(match?: TaskbarSubject | null): void;
export function claimTaskbarPoll(owner: string, subject: TaskbarSubject): void;
export function releaseTaskbarPoll(owner: string): void;
export function taskbarTargetCovered(subject?: TaskbarSubject | null): boolean;
export function publishTaskbarObservation(observation: TaskbarObservation): void;
export function subscribeTaskbarObservations(listener: (observation: TaskbarObservation) => void): () => void;
export function subscribeRunObservations(listener: (observation: TaskbarObservation) => void): () => void;
export type { TaskbarObservation };
export function resetTaskbarRunFeed(): void;
