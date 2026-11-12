/** Marks every node matching `selectors` inert and keeps doing so for nodes
 *  that match later (`watch` calls back when the shell's children change).
 *  Before a node goes inert, focus sitting inside it is handed to
 *  `rescueFocus`, so the browser never drops focus to the body. The returned
 *  release function undoes only what this call set. */
export function applyInertCover({ doc, selectors, rescueFocus, watch }) {
  const marked = new Set();
  let stopWatching = () => undefined;
  const cover = () => {
    const fresh = Array.from(doc.querySelectorAll(selectors.join(','))).filter((node) => !node.inert);
    const focused = doc.activeElement;
    if (focused && fresh.some((node) => node.contains(focused))) rescueFocus();
    fresh.forEach((node) => {
      node.inert = true;
      marked.add(node);
    });
  };
  const release = () => {
    stopWatching();
    marked.forEach((node) => {
      try {
        node.inert = false;
      } catch {
        return;
      }
    });
    marked.clear();
  };
  try {
    cover();
    stopWatching = watch(() => {
      try {
        cover();
      } catch {
        return;
      }
    });
  } catch {
    release();
    return () => undefined;
  }
  return release;
}
