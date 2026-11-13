// FIX-F4 guard: the owner rule bans customer-shaped names in fixtures and tests.
// from repo fixtures and tests. This test scans the in-scope trees and fails
// on any hit, so a reintroduction turns red instead of slipping through.
// .litclaude/ evidence archives are intentionally out of scope (history).
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import test from 'node:test';

const ROOT = new URL('../../', import.meta.url).pathname;
const SCAN_DIRS = ['frontend', 'src', 'tests', 'docs', 'plans'];
const SKIP_DIRS = new Set([
  'node_modules', '.git', '__pycache__', '.venv', '.tox', 'dist', 'build',
  '.litclaude', 'var', '.next', 'target', 'out', '.pytest_cache', '.mypy_cache',
]);
const SKIP_SUFFIXES = ['.pyc', '.png', '.jpg', '.jpeg', '.gif', '.woff', '.woff2', '.ttf', '.ico', '.pdf'];
const SKIP_FILES = new Set(['fixture-names.test.mjs']);
// Built from fragments so this file never matches its own scan.
const BANNED = ['tr' + 'ion', 'e2e' + '_final'].map((source) => new RegExp(source, 'i'));

async function* walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) yield* walk(join(dir, entry.name));
    } else if (entry.isFile()) {
      if (!SKIP_FILES.has(entry.name) && !SKIP_SUFFIXES.some((suffix) => entry.name.endsWith(suffix))) {
        yield join(dir, entry.name);
      }
    }
  }
}

test('repo carries no customer-shaped fixture names', async () => {
  const hits = [];
  for (const top of SCAN_DIRS) {
    for await (const file of walk(join(ROOT, top))) {
      let text;
      try {
        text = await readFile(file, 'utf8');
      } catch {
        continue;
      }
      if (text.includes('\0')) continue;
      text.split('\n').forEach((line, index) => {
        for (const banned of BANNED) {
          if (banned.test(line)) hits.push(`${file}:${index + 1}`);
        }
      });
    }
  }
  assert.deepEqual(hits, [], `customer-shaped fixture names found:\n${hits.join('\n')}`);
});
