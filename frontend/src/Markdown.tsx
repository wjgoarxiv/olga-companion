import type { ReactNode } from 'react';
import { parseMarkdown } from './markdownParser';
import type { Block, Inline } from './markdownParser';
import { formatSignificant, type SignificantFigures } from './significantFigures.mjs';
import { useSignificantFigures } from './useSignificantFigures';

const NUMERIC_CELL = /^[+-]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?(?:e[+-]?\d+)?$/i;

/** Render LLM markdown as a fixed allow-list of React elements. The parser
 *  (markdown.mjs) emits only known node types with string leaves, and this
 *  renderer never uses dangerouslySetInnerHTML, so model output cannot inject
 *  markup or scripts. Links are http(s)-only by construction. */
function renderInline(nodes: Inline[]): ReactNode[] {
  return nodes.map((n, i) => {
    switch (n.type) {
      case 'text':
        return n.value;
      case 'break':
        return <br key={i} />;
      case 'code':
        return <code key={i}>{n.value}</code>;
      case 'strong':
        return <strong key={i}>{renderInline(n.children)}</strong>;
      case 'em':
        return <em key={i}>{renderInline(n.children)}</em>;
      case 'link':
        return (
          <a key={i} href={n.href} target="_blank" rel="noopener noreferrer">
            {renderInline(n.children)}
          </a>
        );
      default:
        return null;
    }
  });
}

function plainText(nodes: Inline[]): string | null {
  return nodes.every((node) => node.type === 'text')
    ? nodes.map((node) => node.type === 'text' ? node.value : '').join('')
    : null;
}

function renderNumericCell(nodes: Inline[], significantFigures: SignificantFigures): ReactNode {
  const text = plainText(nodes)?.trim();
  if (!text || !NUMERIC_CELL.test(text)) return renderInline(nodes);
  return formatSignificant(Number(text.replaceAll(',', '')), significantFigures);
}

function headingTag(level: number): 'h3' | 'h4' | 'h5' | 'h6' {
  if (level <= 3) return 'h3';
  if (level === 4) return 'h4';
  if (level === 5) return 'h5';
  return 'h6';
}

function renderBlock(b: Block, key: number, significantFigures: SignificantFigures): ReactNode {
  switch (b.type) {
    case 'p':
      return <p key={key}>{renderInline(b.children)}</p>;
    case 'heading': {
      const Tag = headingTag(b.level);
      return <Tag key={key}>{renderInline(b.children)}</Tag>;
    }
    case 'code':
      return (
        <pre key={key}>
          <code>{b.value}</code>
        </pre>
      );
    case 'ul':
      return (
        <ul key={key}>
          {b.items.map((it, i) => (
            <li key={i}>{renderInline(it)}</li>
          ))}
        </ul>
      );
    case 'ol':
      return (
        <ol key={key} start={b.start}>
          {b.items.map((it, i) => (
            <li key={i}>{renderInline(it)}</li>
          ))}
        </ol>
      );
    case 'blockquote':
      return <blockquote key={key}>{b.blocks.map((bb, i) => renderBlock(bb, i, significantFigures))}</blockquote>;
    case 'table': {
      const numericColumns = b.header.map((cell) => /\([^)]*\)/.test(plainText(cell) ?? ''));
      return (
        <div key={key} className="md-table-wrap">
          <table>
            <thead>
              <tr>
                {b.header.map((c, i) => (
                  <th key={i}>{renderInline(c)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {b.rows.map((r, ri) => (
                <tr key={ri}>
                  {r.map((c, ci) => (
                    <td key={ci}>{numericColumns[ci] ? renderNumericCell(c, significantFigures) : renderInline(c)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    default:
      return null;
  }
}

export default function Markdown({ text, className }: { text: string; className?: string }) {
  const significantFigures = useSignificantFigures();
  const blocks = parseMarkdown(text);
  return <div className={className ? `md ${className}` : 'md'}>{blocks.map((b, i) => renderBlock(b, i, significantFigures))}</div>;
}
