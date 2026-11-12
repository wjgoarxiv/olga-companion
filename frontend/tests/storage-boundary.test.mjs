import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('browser storage denial cannot escape the shared persistence boundary', async () => {
  // Given every component that persists non-authoritative UI preferences.
  const consumers = await Promise.all([
    read('../src/App.tsx'),
    read('../src/FlowpathDetailPanel.tsx'),
    read('../src/PanelResizeHandle.tsx'),
    read('../src/useActiveWorkQueue.ts'),
    read('../src/useChatSessions.ts'),
    read('../src/appearance.ts'),
    read('../src/shell/useWorkbenchLayout.ts'),
    read('../src/shell/HeightResizer.tsx'),
  ]);

  // When persistence calls are inspected.
  // Then components never call the throwable browser API directly.
  assert.doesNotMatch(consumers.join('\n'), /\blocalStorage\.(?:getItem|setItem|removeItem)\b/);

  const boundary = await read('../src/safeLocalStorage.ts');
  assert.match(boundary, /export function readLocalStorage/);
  assert.match(boundary, /export function writeLocalStorage/);
  assert.match(boundary, /export function removeLocalStorage/);
  assert.match(boundary, /catch \{/);
});

test('a throwing localStorage degrades to defaults instead of raising', async () => {
  const { readLocalStorage, removeLocalStorage, writeLocalStorage } = await import('../src/safeLocalStorage.ts');
  const denied = () => { throw new DOMException('denied', 'SecurityError'); };
  const original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { getItem: denied, setItem: denied, removeItem: denied },
  });
  try {
    assert.equal(readLocalStorage('olga_view'), null);
    assert.doesNotThrow(() => writeLocalStorage('olga_view', 'chat'));
    assert.doesNotThrow(() => removeLocalStorage('olga_view'));
  } finally {
    if (original) Object.defineProperty(globalThis, 'localStorage', original);
    else delete globalThis.localStorage;
  }
});
