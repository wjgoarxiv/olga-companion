import GlossaryTerm from './GlossaryTerm';
import { glossaryTermFor } from './caseEditGlossary.mjs';

/** The OLGA KEYWORD.KEY a row changes, as a caption that opens its glossary entry when there is one. */
export default function KeywordCaption({ keyword }: { readonly keyword?: string }) {
  if (!keyword) return null;
  const term = glossaryTermFor(keyword);
  return (
    <small className="case-edit-keyword">
      {term ? <GlossaryTerm term={term} label={keyword}>{keyword}</GlossaryTerm> : keyword}
    </small>
  );
}
