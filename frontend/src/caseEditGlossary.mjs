// Glossary entries are keyed by the bare key name and were written for one keyword. A key whose
// entry describes it under another keyword is not looked up here, so its caption shows alone.
const OTHER_KEYWORD = new Set(['PROFILE.DTPLOT']);

/** The glossary term for an edit-table KEYWORD.KEY caption, or null when none should be shown. */
export function glossaryTermFor(keyword) {
  if (typeof keyword !== 'string' || OTHER_KEYWORD.has(keyword)) return null;
  const key = keyword.split('.')[1];
  return key ? key : null;
}
