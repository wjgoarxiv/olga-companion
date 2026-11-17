export type UpdateStageId =
  | 'checking'
  | 'available'
  | 'downloading'
  | 'verifying'
  | 'installing'
  | 'restarting';

export type UpdateStageState = 'todo' | 'active' | 'done' | 'failed' | 'blocked';

export const UPDATE_STAGES: readonly UpdateStageId[];

export function keepsUpdateHandle(phase: { readonly kind: string } | null | undefined): boolean;

export function stageOfPhase(phase: {
  readonly kind: string;
  readonly stage?: UpdateStageId | null;
  readonly backendStopped?: boolean;
}): {
  readonly states: Record<UpdateStageId, UpdateStageState>;
  readonly active: UpdateStageId | null;
  readonly failed: UpdateStageId | null;
  readonly blocked: UpdateStageId | null;
};
