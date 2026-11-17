import type { Topology, WorkspaceCase } from './session';

export function loadWorkspaceCase(
  workspaceCase: WorkspaceCase,
  options: { readonly activate: boolean },
  dependencies: {
    readonly activate: (rel: string) => void | Promise<void>;
    readonly fetchTopology: (rel: string) => Promise<Topology>;
  },
): Promise<Topology>;

type WorkspaceDependencies = {
  readonly activate: (rel: string) => void | Promise<void>;
  readonly fetchTopology: (rel: string) => Promise<Topology>;
};

type WorkspaceHydrationObserver = {
  readonly onStart: (workspaceCase: WorkspaceCase) => void;
  readonly onSuccess: (topology: Topology) => void;
  readonly onError: (error: Error) => void;
  readonly onSettled: () => void;
};

export function createWorkspaceHydration(
  dependencies: WorkspaceDependencies,
  observer: WorkspaceHydrationObserver,
): {
  readonly setup: (workspaceCase: WorkspaceCase) => {
    readonly task: Promise<void>;
    readonly cleanup: () => void;
  };
  readonly activate: (workspaceCase: WorkspaceCase) => Promise<void>;
  readonly invalidate: () => void;
};
