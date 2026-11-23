export type LocalCliState = 'loading' | 'not_found' | 'found' | 'needs_sign_in' | 'ready' | 'problem';
export type LocalCliCode = { readonly code: string; readonly message_ko: string; readonly message_en: string };
export function localCliView(
  status: LocalCliCode | null,
  check: LocalCliCode | null,
): { state: LocalCliState; titleKey: string | null; stepKey: string | null; showCommand: boolean };
export function localCliMessage(result: LocalCliCode | null, locale: string): string;
export function localCliBillingKey(billing: string | undefined): string | null;
