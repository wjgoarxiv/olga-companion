// One reader for numbers a person types: plain decimals only, ambiguous text refused.
// Same rules as src/olga_companion/strict_number.py; tests/fixtures/strict_number_cases.json holds both.

const PLAIN = /^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$/;
const COMMA = /^[-+]?(?:\d+,\d+|,\d+)(?:[eE][-+]?\d+)?$/;
const THOUSANDS = /^[-+]?\d{1,3}(?:,\d{3})+$/;

/** The finite number the text plainly says, or null ("1,500", "0x10", "1_000", "Infinity" are refused). */
export function parseStrictNumber(value, { decimalComma = true } = {}) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value !== 'string') return null;
  const text = value.trim();
  let number;
  if (PLAIN.test(text)) number = Number(text);
  else if (decimalComma && COMMA.test(text) && !THOUSANDS.test(text)) number = Number(text.replace(',', '.'));
  else return null;
  return Number.isFinite(number) ? number : null;
}
