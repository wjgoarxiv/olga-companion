import { useEffect, useRef } from 'react';
import { openFromRun } from '../editFromRunModel.mjs';
import { EDIT_FROM_RUN_EVENT, parseEditFromRun, requestCaseEdit } from './workspaceEvents';

/** A result's "Edit from this run": make its case active, then open the value table on it with
 *  nothing typed in. The latest callbacks are read at click time, so the workspace generation is current. */
export function useEditFromRun(activeName: string | null, pickCase: (rel: string) => Promise<boolean>, openWorkspace: () => void): void {
  const latest = useRef({ activeName, pickCase, openWorkspace });
  latest.current = { activeName, pickCase, openWorkspace };
  useEffect(() => {
    function handleEditFromRun(event: Event) {
      const target = parseEditFromRun(event);
      if (!target) return;
      void openFromRun(target, {
        ...latest.current,
        request: (rel) => window.dispatchEvent(requestCaseEdit({ rel })),
      });
    }
    window.addEventListener(EDIT_FROM_RUN_EVENT, handleEditFromRun);
    return () => window.removeEventListener(EDIT_FROM_RUN_EVENT, handleEditFromRun);
  }, []);
}
