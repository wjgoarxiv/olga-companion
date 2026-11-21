import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const inventory = fs.readFileSync(path.join(root, 'src', 'ResultsInventoryRail.tsx'), 'utf8');

test('result inventory exposes the current selection and complete row identity', () => {
  assert.match(
    inventory,
    /aria-current=\{selected\?\.id === f\.id \? 'true' : undefined\}/,
    'the visually active result must also expose its current-item state',
  );
  assert.match(
    inventory,
    /aria-label=\{`\$\{f\.name\}, \$\{context\}, \$\{\(f\.size \/ 1024\)\.toFixed\(0\)\} KB`\}/,
    'each repeated filename needs one explicit, complete accessible identity',
  );
});
