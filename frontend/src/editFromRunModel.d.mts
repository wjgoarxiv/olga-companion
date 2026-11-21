export type EditSource = { readonly rel?: string; readonly reason?: string };
export type EditFromRun = { readonly kind: 'open'; readonly rel: string } | { readonly kind: 'reason'; readonly key: string };

export function editFromRun(result: { readonly edit_source?: EditSource } | null | undefined): EditFromRun | null;
export function openFromRun(rel: string, deps: {
  readonly activeName: string | null;
  readonly pickCase: (rel: string) => Promise<boolean | void>;
  readonly openWorkspace: () => void;
  readonly request: (rel: string) => void;
}): Promise<boolean>;
export function editTargetStep(input: {
  readonly target: { readonly rel: string } | null;
  readonly selected: string | null;
  readonly activeRel: string | null;
  readonly activeAtRequest: string | null;
}): 'open' | 'wait' | 'drop';
