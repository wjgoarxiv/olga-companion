/** Workspace view events: the shell Explorer asks the case surface to preview a
    PVT table without changing the active case (mirrors artifactNavigation). */

export const OPEN_TAB_PREVIEW_EVENT = 'olga:open-tab-preview';
const TAB_REL_KEY = 'rel';

/** Request a read-only PVT preview for a workspace-relative path. */
export function requestTabPreview(rel: string): CustomEvent {
  return new CustomEvent(OPEN_TAB_PREVIEW_EVENT, { detail: { [TAB_REL_KEY]: rel } });
}

/** Read the requested path from a preview request; null for anything else. */
export function parseTabPreviewEvent(event: Event): string | null {
  if (!(event instanceof CustomEvent)) return null;
  if (event.type !== OPEN_TAB_PREVIEW_EVENT) return null;
  const detail = event.detail as { [TAB_REL_KEY]?: unknown } | null;
  const rel = detail?.[TAB_REL_KEY];
  return typeof rel === 'string' && rel.length > 0 ? rel : null;
}

/** The step bar's Edit action asks the Workspace view to open the value table for the active case.
    The request is also staged, because the Workspace view may mount only after the view switch. */
export const OPEN_CASE_EDIT_EVENT = 'olga:open-case-edit';
let stagedCaseEdit = false;

/** Open the table only for this case, with this row marked when a stopped run names one. */
export type CaseEditTarget = { readonly rel: string; readonly rowId?: string };

/** A result asks the app to make its run's case active and open the value table on it. */
export const EDIT_FROM_RUN_EVENT = 'olga:edit-from-run';

export function requestEditFromRun(rel: string): CustomEvent {
  return new CustomEvent(EDIT_FROM_RUN_EVENT, { detail: { rel } });
}

/** The case path of an edit-from-run request; null for anything else. */
export function parseEditFromRun(event: Event): string | null {
  if (!(event instanceof CustomEvent) || event.type !== EDIT_FROM_RUN_EVENT) return null;
  const rel = (event.detail as { rel?: unknown } | null)?.rel;
  return typeof rel === 'string' && rel.length > 0 ? rel : null;
}
let stagedTarget: CaseEditTarget | null = null;

export function requestCaseEdit(target: CaseEditTarget | null = null): CustomEvent {
  stagedCaseEdit = true;
  stagedTarget = target;
  return new CustomEvent(OPEN_CASE_EDIT_EVENT);
}

/** The row a staged request points at, once; null for the step bar's plain Edit action. */
export function consumeCaseEditTarget(): CaseEditTarget | null {
  const target = stagedTarget;
  stagedTarget = null;
  return target;
}

/** True once per staged request; the caller opens the table for the case it shows. */
export function consumeStagedCaseEdit(): boolean {
  const staged = stagedCaseEdit;
  stagedCaseEdit = false;
  return staged;
}

/** The value table changed which case is active (saved a copy, or went back to the original). */
export const CASE_EDIT_ACTIVE_CHANGED_EVENT = 'olga:case-edit-active-changed';

/** The value table saved an approved copy; detail.rel is the new copy's workspace path. */
export const CASE_EDIT_SAVED_EVENT = 'olga:case-edit-saved';
