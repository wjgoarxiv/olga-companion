interface CoverNode {
  inert?: boolean;
  contains(other: unknown): boolean;
}

export declare function applyInertCover(options: {
  readonly doc: {
    readonly activeElement: unknown;
    querySelectorAll(selector: string): ArrayLike<CoverNode> | Iterable<CoverNode>;
  };
  readonly selectors: readonly string[];
  readonly rescueFocus: () => void;
  readonly watch: (onChange: () => void) => () => void;
}): () => void;
