import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

/* Settings is a sectioned page: the left list names every section, arrow
   keys move and Enter activates, and the choice survives tab switches. */

test('settings lists its seven sections with arrow-key roving and aria-current', async () => {
  const view = await read('../src/SettingsView.tsx');

  for (const section of ['general', 'provider', 'apikey', 'workspace', 'network', 'updates', 'support']) {
    assert.match(view, new RegExp(`'${section}'`), `section ${section} exists`);
    assert.match(view, new RegExp(`settings\\.section${section[0].toUpperCase()}${section.slice(1)}`), `section ${section} reads its label from the dictionary`);
  }
  assert.match(view, /aria-current=\{[^}]*\}/, 'the active section exposes aria-current');
  assert.match(view, /onKeyDown/, 'the section list handles arrow keys');
  assert.match(view, /ArrowDown/, 'arrow down moves through sections');
  assert.match(view, /ArrowUp/, 'arrow up moves through sections');
  assert.match(view, /tabIndex=\{[^}]*\}/, 'section buttons rove their tab stop');
});

test('the selected section is remembered for the session', async () => {
  const view = await read('../src/SettingsView.tsx');

  assert.match(view, /rememberedSection/, 'the selection lives outside render state');
  assert.doesNotMatch(view, /localStorage.*[Ss]ection/, 'section memory is session-scoped, not persisted');
});

test('theme and density choices persist across reload', async () => {
  const appearance = await read('../src/appearance.ts');

  assert.match(appearance, /DENSITY_KEY/, 'density has a storage key');
  assert.match(appearance, /loadDensity|parseDensity/, 'stored density is read back');
  assert.match(appearance, /applyDensityAttribute|data-density/, 'density reaches the document');
  assert.match(appearance, /initAppearance[\s\S]*?loadDensity|loadDensity[\s\S]*?initAppearance/, 'startup restores density');
});

test('settings controls stay inside their cards', async () => {
  const css = await read('../src/styles/settings.css');

  assert.match(css, /\.settings-section-panel[^{]*\binput\b[^{]*\{[^}]*min-width:\s*0/s, 'panel inputs may not force intrinsic width');
  assert.match(css, /\.settings-section-panel[^{]*\binput\b[^{]*\{[^}]*width:\s*100%/s, 'panel inputs fill their track');
  assert.match(css, /\.settings-section-panel[^{]*\bselect\b[^{]*\{[^}]*width:\s*100%/s, 'panel selects fill their track');
});

test('the two-column shell collapses on the panel width, not the viewport', async () => {
  const css = await read('../src/styles/settings.css');

  assert.match(css, /@container\s*\([^)]*max-width:\s*560px[^)]*\)[\s\S]*?\.settings-layout\s*\{\s*grid-template-columns:\s*minmax\(0,\s*1fr\)/s, 'a narrow tab panel stacks the section list above the cards');
});

test('disabled buttons never fade the whole element', async () => {
  const css = await read('../src/styles/controls.css');

  const rule = css.match(/\.ui-button:disabled\s*\{[^}]*\}/s);
  assert.ok(rule, 'the shared disabled rule exists');
  assert.doesNotMatch(rule[0], /opacity:\s*0?\.[0-9]\b/, 'no whole-element fade at all');
  assert.doesNotMatch(rule[0], /dashed/, 'disabled reads as a solid control, never a dashed outline');
  assert.match(rule[0], /var\(--btn-disabled-(bg|text|border)\)/, 'disabled reuses the shared triple');
});
