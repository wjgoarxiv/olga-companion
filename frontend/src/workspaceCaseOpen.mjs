export async function loadWorkspaceCase(workspaceCase, options, dependencies) {
  if (options.activate) await dependencies.activate(workspaceCase.rel);
  return dependencies.fetchTopology(workspaceCase.rel);
}

export function createWorkspaceHydration(dependencies, observer) {
  let epoch = 0;

  function start(workspaceCase, activate) {
    const request = ++epoch;
    observer.onStart(workspaceCase);
    const task = (async () => {
      try {
        const topology = await loadWorkspaceCase(workspaceCase, { activate }, dependencies);
        if (request !== epoch) return;
        observer.onSuccess(topology);
      } catch (cause) {
        if (request !== epoch) return;
        observer.onError(cause instanceof Error ? cause : new Error(String(cause)));
      } finally {
        if (request === epoch) observer.onSettled();
      }
    })();
    return { request, task };
  }

  return {
    setup(workspaceCase) {
      const started = start(workspaceCase, false);
      let cleaned = false;
      return {
        task: started.task,
        cleanup() {
          if (cleaned) return;
          cleaned = true;
          if (epoch === started.request) epoch += 1;
        },
      };
    },
    activate(workspaceCase) {
      return start(workspaceCase, true).task;
    },
    invalidate() {
      epoch += 1;
    },
  };
}
