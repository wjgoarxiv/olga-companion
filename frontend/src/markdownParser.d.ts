// Types for the dependency-free markdown parser (markdown.mjs). Kept alongside
// the .mjs so Markdown.tsx type-checks while node:test runs the .mjs directly.
export type Inline =
  | { type: 'text'; value: string }
  | { type: 'code'; value: string }
  | { type: 'strong'; children: Inline[] }
  | { type: 'em'; children: Inline[] }
  | { type: 'link'; href: string; children: Inline[] }
  | { type: 'break' };

export type Block =
  | { type: 'p'; children: Inline[] }
  | { type: 'heading'; level: number; children: Inline[] }
  | { type: 'code'; value: string }
  | { type: 'ul'; items: Inline[][] }
  | { type: 'ol'; start: number; items: Inline[][] }
  | { type: 'blockquote'; blocks: Block[] }
  | { type: 'table'; header: Inline[][]; rows: Inline[][][] };

export function parseMarkdown(src: string): Block[];
export function parseInline(text: string): Inline[];
