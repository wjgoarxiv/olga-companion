export declare const SHUTDOWN_STAGES: readonly string[];

export declare function stageProgress(stage: string): number;

export declare function startPhase(options: { hasActiveRun: boolean }): string;

export interface ShutdownFlow {
  event(name: string, detail?: string | null): string;
  phase(): string;
  reason(): string | null;
}

export declare function createShutdownFlow(options?: { hasActiveRun?: boolean }): ShutdownFlow;
