export interface TutorialStep {
  readonly id: string;
  readonly target: string;
  readonly textKey: string;
  readonly event: string;
}

export type TutorialStatus = 'idle' | 'active' | 'paused' | 'skipped' | 'done';

export interface TutorialState {
  readonly version: 1;
  readonly status: TutorialStatus;
  readonly index: number;
  readonly finishedWithoutOlga: boolean;
}

export interface TutorialStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export declare const TUTORIAL_STORAGE_KEY: string;
export declare const TUTORIAL_OPEN_EVENT: string;
export declare const TUTORIAL_CHANGE_EVENT: string;
export declare const TUTORIAL_EVENTS: {
  readonly WORKSPACE_CHOSEN: string;
  readonly CASE_CREATED: string;
  readonly VALIDATION_DONE: string;
  readonly VALIDATION_READ: string;
  readonly RUN_STARTED: string;
  readonly RUN_FINISHED: string;
  readonly RESULTS_OPENED: string;
  readonly NO_OLGA: string;
};
export declare const NO_OLGA_STEP_ID: string;
export declare const TUTORIAL_STEPS: readonly TutorialStep[];
export declare const TOUR_FALLBACK_SELECTORS: Readonly<Record<string, string>>;
export declare function tourTargetSelectors(target: string): readonly string[];
export declare function resolveTourTarget<T extends { closest?: (selector: string) => T | null }>(
  target: string,
  query: (selector: string) => T | null,
  usable?: (element: T) => boolean,
): T | null;
export declare function resumeChipPending(state: TutorialState, acknowledged: boolean): boolean;
export declare function initialTutorialState(): TutorialState;
export declare function startTutorial(state: TutorialState): TutorialState;
export declare function pauseTutorial(state: TutorialState): TutorialState;
export declare function resumeTutorial(state: TutorialState): TutorialState;
export declare function skipTutorial(state: TutorialState): TutorialState;
export declare function resetTutorial(state: TutorialState): TutorialState;
export declare function advanceTutorial(state: TutorialState, event: string): TutorialState;
export declare function isTutorialFinished(state: TutorialState): boolean;
export declare function loadTutorialState(storage?: TutorialStorage | undefined): TutorialState;
export declare function saveTutorialState(state: TutorialState, storage?: TutorialStorage | undefined): boolean;
export declare function requestTutorialOpen(): void;
export declare function notifyTutorialChanged(): void;
export declare function stepAction(stepId: string): {
  readonly kind: 'install-demo' | 'focus-workspace' | 'validate' | 'show-problems' | 'open-run' | 'open-results';
  readonly labelKey: string;
} | null;
export declare function tutorialStepSatisfied(stepId: string, facts: {
  readonly workspaceRoot?: string;
  readonly activeCaseName?: string | null;
  readonly installedCaseName?: string | null;
  readonly validatedCaseName?: string | null;
  readonly validationOk?: boolean;
  readonly validationRead?: boolean;
  readonly runStartedForCase?: boolean;
  readonly runFinishedForCase?: boolean;
  readonly resultsOpenedForCase?: boolean;
}): boolean;
export declare function freshRunIds(ids: Iterable<string>, baseline: { has(value: string): boolean }): string[];
