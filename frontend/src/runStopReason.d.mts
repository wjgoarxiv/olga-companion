export type StopReason = {
  readonly code: string;
  readonly stopped_at_s?: number | null;
  readonly pressure_bara?: number | null;
  readonly temperature_c?: number | null;
  readonly where?: string | null;
  readonly exit_code?: number | null;
  readonly exit_message?: string | null;
  readonly last_lines?: readonly string[];
};
export type StopReasonView = {
  readonly known: boolean;
  readonly titleKey: string;
  readonly detailKey: string;
  readonly params: Record<string, string>;
  readonly stepKeys: readonly string[];
  readonly lastLines: readonly string[];
};
export function stopReasonView(reason: StopReason | null | undefined): StopReasonView | null;
export function stopReasonPrompt(reason: StopReason | null | undefined, caseName: string | null | undefined): string;
