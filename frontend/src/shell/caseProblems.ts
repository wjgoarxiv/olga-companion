/** Shared case-problem bus: the case surface publishes validation and PVT
    findings, the bottom Problems panel subscribes, and a problem row focuses
    its topology node through a typed window event (mirrors artifactNavigation).
    Framework-free so node tests import it directly; components subscribe with
    useSyncExternalStore. */

export type CaseProblemSeverity = 'error' | 'warning' | 'info';
export type CaseProblemSource = 'validation' | 'pvt' | 'topology' | 'flowpath';

export interface CaseProblem {
  readonly id: string;
  readonly severity: CaseProblemSeverity;
  readonly title: string;
  readonly detail?: string;
  readonly source: CaseProblemSource;
  /** Topology node id when the finding points at one; otherwise null. */
  readonly nodeId: string | null;
}

export const FOCUS_TOPOLOGY_NODE_EVENT = 'olga:focus-topology-node';
const FOCUS_NODE_KEY = 'nodeId';

let problems: readonly CaseProblem[] = [];
const listeners = new Set<(problems: readonly CaseProblem[]) => void>();

function notify() {
  for (const listener of [...listeners]) listener(problems);
}

/** Replace the published problem list (call with [] when the case closes). */
export function publishCaseProblems(next: readonly CaseProblem[]): void {
  problems = next;
  notify();
}

/** Clear every published problem. */
export function resetCaseProblems(): void {
  problems = [];
  notify();
}

function snapshot(): readonly CaseProblem[] {
  return problems;
}

/** Subscribe to the problem list; returns an unsubscribe function. */
export function subscribeCaseProblems(listener: (problems: readonly CaseProblem[]) => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** React binding for the problem list. */
export function getCaseProblemsSnapshot(): readonly CaseProblem[] {
  return snapshot();
}

/** Request the topology map to select and reveal a node. */
export function focusTopologyNode(nodeId: string): CustomEvent {
  return new CustomEvent(FOCUS_TOPOLOGY_NODE_EVENT, { detail: { [FOCUS_NODE_KEY]: nodeId } });
}

/** Read the node id from a focus request; null for anything else. */
export function parseFocusNodeEvent(event: Event): string | null {
  if (!(event instanceof CustomEvent)) return null;
  if (event.type !== FOCUS_TOPOLOGY_NODE_EVENT) return null;
  const detail = event.detail as { [FOCUS_NODE_KEY]?: unknown } | null;
  const nodeId = detail?.[FOCUS_NODE_KEY];
  return typeof nodeId === 'string' && nodeId.length > 0 ? nodeId : null;
}
