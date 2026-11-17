import type { AgentEvent } from './types';

export const DRAFT_LIMIT: number;
export function reduceDraft(draft: string, event: AgentEvent): string;
export function draftToShow(draft: string): string | null;
