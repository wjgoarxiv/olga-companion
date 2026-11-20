import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { isAllowListed, loadAllowlist, scanDataSource, scanSource, templateStaticText } from '../../scripts/find_untranslated_ui.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const SCRIPT = resolve(HERE, '..', '..', 'scripts', 'find_untranslated_ui.mjs');
const FIXTURES = resolve(HERE, 'fixtures', 'data-sweep');

test('data sweep reports an unrouted Hangul literal in a .ts file', () => {
  const run = spawnSync(process.execPath, [SCRIPT, '--root', FIXTURES], { encoding: 'utf8' });
  assert.equal(run.status, 1, `data sweep should exit 1 on the fixture tree:\n${run.stdout}`);
  assert.match(run.stdout, /안녕 세계/, 'the Hangul literal is reported');
  assert.match(run.stdout, /not routed through t/, 'the English sentence is reported');
});

test('data sweep skips t() fallbacks after ??', () => {
  assert.deepEqual(scanDataSource('const x = t("run.ready") ?? "fallback copy";'), []);
  assert.deepEqual(scanDataSource("const x = text('run.ready') ?? '대기 중';"), []);
});

test('data sweep flags bare Hangul and English sentences alike', () => {
  assert.equal(scanDataSource("export const note = '안녕 세계';").length, 1);
  assert.equal(scanDataSource('export const note = "Hello world today";').length, 1);
  assert.deepEqual(scanDataSource('export const code = "run_ready";'), []);
  assert.deepEqual(scanDataSource('export const label = "PT";'), []);
});

test('data sweep judges template wording, not code inside ${}', () => {
  assert.equal(templateStaticText('`M${x},${y} C${a},${b}`'), 'M, C,');
  assert.equal(templateStaticText('`${k}: ${v}`'), ': ');
  assert.equal(scanDataSource('const d = `M${x},${y} C${a},${b}`;').length, 1);
  assert.deepEqual(scanDataSource('const q = `?${params}`;'), []);
  assert.deepEqual(scanDataSource('const u = `/api/run/${id}`;'), []);
  assert.equal(scanDataSource('const s = `Invalid ${field}.`;').length, 1);
  assert.equal(scanDataSource('const s = `이 승인은 ${hh}까지 유효합니다`;').length, 1);
});

test('tsx scan tracks elements inside expression containers (H1)', () => {
  const nested = 'const A = () => <div>{ok && <span>Hangul inside</span>}</div>;';
  const found = scanSource(nested).filter((f) => f.text.includes('Hangul inside'));
  assert.equal(found.length, 1, 'element text in && is scanned once');
  assert.equal(found[0].text, 'Hangul inside', 'the run stops at the expression boundary');
  const ternary = 'const B = () => <div>{ok ? <p>참 거짓</p> : <p>else</p>}</div>;';
  const branch = scanSource(ternary).filter((f) => f.text.includes('참 거짓'));
  assert.equal(branch.length, 1);
  assert.equal(branch[0].text, '참 거짓', 'else-branch code stays out of the text');
});

test('tsx scan reports quoted script literals outside JSX tags (H2)', () => {
  const src = "const LABEL = 'Hangul words here';\nexport const A = () => <div/>;";
  assert.equal(scanSource(src).filter((f) => f.text === 'Hangul words here').length, 1);
});

test('tsx scan stops element text at attribute-expression boundaries', () => {
  const src = 'const A = () => <S title="t" action={<Button busy={b} busyLabel="Busy…">Retry figure</Button>} />;';
  const texts = scanSource(src).map((f) => f.text);
  assert.ok(texts.includes('Retry figure'), 'button text inside attr expression is scanned');
  assert.ok(!texts.some((t) => t.includes('}') && t.includes('Retry figure')), 'no brace tail leaks into the text');
});

test('tsx scan reports quoted branches inside JSX expressions (H2)', () => {
  const src = "const A = () => <strong>{good ? '사례 명세' : '확인 필요'}</strong>;";
  const texts = scanSource(src).map((f) => f.text);
  assert.ok(texts.includes('사례 명세'), 'ternary branch quoted literal is scanned');
  assert.ok(texts.includes('확인 필요'), 'ternary else quoted literal is scanned');
});

test('tsx scan reports template attrs for visible props (H2)', () => {
  const src = 'const A = () => <W description={`원본 폴더 ${x} 읽기`} kicker="준비" />;';
  const texts = scanSource(src).map((f) => f.text);
  assert.ok(texts.some((t) => t.includes('원본 폴더')), 'visible template attr is scanned');
  assert.ok(texts.includes('준비'), 'visible quoted attr is scanned');
});

test('tsx scan reports quoted branches in visible-attr expressions (H2)', () => {
  const src = "const A = () => <W title={ok ? '고르기' : '없음'} onClick={() => pick('x')} />;";
  const texts = scanSource(src).map((f) => f.text);
  assert.ok(texts.includes('고르기'), 'visible attr ternary branch is scanned');
  assert.ok(texts.includes('없음'), 'visible attr ternary else is scanned');
});

test('nullish fallback only exempts t()/text()/translate() calls (M6)', () => {
  assert.equal(scanDataSource("const x = foo ?? 'fallback words here';").length, 1);
  assert.equal(scanDataSource("const x = bar('k') ?? 'fallback words here';").length, 1);
  assert.deepEqual(scanDataSource("const x = t('k') ?? 'fallback words here';"), []);
  assert.deepEqual(scanDataSource("const x = text('k') ?? 'fallback words here';"), []);
  assert.deepEqual(scanDataSource("const x = translate('en', 'k') ?? 'fallback words here';"), []);
});

test('mixed allow-list sentence still flagged (L7)', () => {
  assert.equal(isAllowListed('Save OLGA .tab', ['OLGA', '.tab']), false);
});

test('data sweep allow-list entries still excuse data findings', () => {
  const entries = loadAllowlist(resolve(HERE, '..', '..', 'frontend', 'i18n-allowlist.json'));
  assert.ok(entries.length > 0, 'the production allow-list loads');
  assert.equal(isAllowListed('OLGA', entries), true);
});

test('tsx scan flags the new primitives\u2019 visible props (ariaLabel, hint, error, badge)', () => {
  const src = 'const A = () => <Panel ariaLabel="Unrouted panel label"><Field label="Type the name" hint="Use plain words" error="Value is missing" /><Tabs badge="Three items" /></Panel>;';
  const attrs = scanSource(src).filter((f) => f.kind === 'attr').map((f) => f.attr).sort();
  assert.deepEqual(attrs, ['ariaLabel', 'badge', 'error', 'hint', 'label'], 'every visible prop is scanned');
  assert.deepEqual(scanSource('const A = () => <Panel ariaLabel={t("panel.files")}><Field label={t("field.name")} /></Panel>;').filter((f) => f.kind === 'attr'), [], 't() props stay quiet');
});

test('data sweep flags a capitalised single English word', () => {
  assert.equal(scanDataSource('export const label = "Save";').length, 1, 'bare Save is visible copy');
  assert.equal(scanDataSource("export const label = 'Cancel';").length, 1, 'bare Cancel is visible copy');
  assert.equal(scanSource("const A = () => <B title={ok ? 'Retry' : 'Later'} />;").filter((f) => f.text === 'Retry').length, 1, 'bare Retry in an expression is visible copy');
  assert.deepEqual(scanDataSource('export const code = "OLGA";'), [], 'all-caps brand stays quiet');
  assert.deepEqual(scanDataSource('export const code = "run_ready";'), [], 'snake code stays quiet');
  assert.deepEqual(scanDataSource('export const label = "PT";'), [], 'short units stay quiet');
  assert.deepEqual(scanDataSource('export const flag = "true";'), [], 'lowercase tokens stay quiet');
});
