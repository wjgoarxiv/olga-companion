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
