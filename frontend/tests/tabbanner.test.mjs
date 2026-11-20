// W3-L3 RED-first: M4 '.tab 없음' banner + T5 fluid-table flow.
// Static pins (no browser): registration, R-cleared copy, button sets +
// degrade path, empty start, documented models/units, preview-before-save
// ordering, zero send/save/run/approval on activation, generic manual steps,
// ko+en resolution with no Hangul in en.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { translate } from '../src/i18n/index.ts';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('M4 FIX: create-fluid-table is registered (keymap, palette, handler)', async () => {
  const [keymap, commands, hook] = await Promise.all([
    read('../src/shell/keymap.ts'),
    read('../src/shell/commands.ts'),
    read('../src/shell/useWorkbenchCommands.ts'),
  ]);
  assert.match(keymap, /\| 'create-fluid-table'/, 'ShellCommandId carries create-fluid-table');
  assert.match(commands, /id: 'create-fluid-table'/, 'palette registry carries the command');
  assert.match(commands, /labelKey: 'tabbanner\.create'/, 'palette label resolves through the dictionary');
  assert.match(hook, /id === 'create-fluid-table'/, 'runCommand handles the T5 route');
  assert.match(hook, /selectView\('workspace'\)/, 'T5 route lands on the workspace view');
  assert.match(hook, /requestFluidTableFlow\(\)/, 'T5 route opens the flow (explicit click only)');
  assert.match(hook, /CREATE_FLUID_TABLE_EVENT/, 'the W2-L1 ①-entry event is registered here');
});

test('M4 banner: R-cleared copy, 3 buttons with the flow, 2 without', async () => {
  const slot = await read('../src/shell/StepBarSlot.tsx');
  assert.match(slot, /tabbanner\.need/, 'banner title key');
  assert.match(slot, /tabbanner\.how/, 'banner body key');
  assert.match(slot, /tabbanner\.create/, 'primary 만들기 key (T5 id path)');
  assert.match(slot, /tabbanner\.openWorkspace/, 'secondary Workspace 열기 key');
  assert.match(slot, /tabbanner\.preview/, 'preview key (enabled when a .tab exists)');
  assert.match(slot, /onRunCommand\('create-fluid-table'\)/, 'primary routes through the T5 command id only');
  assert.match(slot, /onSelectView\('workspace'\)/, 'Workspace 열기 routes through the existing selector');
  assert.match(slot, /SHELL_COMMANDS/, 'banner degrades on the flow-entry capability, never a dead button');
  assert.match(slot, /tabCases\.length === 0/, 'banner shows when the workspace has no .tab');
  assert.match(slot, /pvtUnresolvable|pvt_reference/, 'banner degrades to unresolvable pvt_reference');
});

test('T5 flow starts empty: no model default, no composition, live sum', async () => {
  const [flow, css] = await Promise.all([
    read('../src/shell/FluidTableFlow.tsx'),
    read('../src/styles/fluid-table-flow.css'),
  ]);
  assert.match(css, /\.fluid-flow\s*\{[^}]*position:\s*fixed/s, 'the flow overlays instead of pushing the workbench');
  assert.match(css, /max-height:\s*calc\(100dvh/, 'the dialog sizes to content up to a viewport cap');
  assert.match(flow, /useState<string \| null>\(null\)|useState<.*model.*>\(''/, 'no EOS model is preselected');
  for (const model of ['PR', 'PRA', 'SRK', 'RKSA', 'CPA']) {
    assert.match(flow, new RegExp(`['"]${model}['"]`), `model choice offers ${model}`);
  }
  assert.doesNotMatch(flow, /useState\(\[\s*\{[^}]*name:\s*['"][^'"]+['"]/s, 'no preset component rows');
  assert.match(flow, /moleSum|fractionSum|sum.*1\.0|total/i, 'a live mole-fraction sum is shown');
  assert.match(flow, /temperature_unit|temperatureUnit/, 'temperature unit is an explicit choice');
  assert.match(flow, /pressure_unit|pressureUnit/, 'pressure unit is an explicit choice');
  for (const unit of ['degC', 'bar', 'barg']) {
    assert.match(flow, new RegExp(`['"]${unit}['"]`), `unit list carries ${unit}`);
  }
});

test('T5 order: preview before save; save and link go through the draft path', async () => {
  const [flow, api] = await Promise.all([
    read('../src/shell/FluidTableFlow.tsx'),
    read('../src/workspaceApi.ts'),
  ]);
  assert.match(flow, /fluidsDraftPreview/, 'preview calls the read-only draft endpoint');
  assert.match(api, /\/api\/fluids\/draft-preview/, 'preview hits the read-only draft route');
  assert.match(api, /writes_nothing/, 'the draft contract writes nothing');
  assert.match(flow, /disabled.*preview|preview.*disabled|!preview/i, 'save waits for a good preview');
  assert.match(flow, /setInput/, 'save hands the validated draft to the composer (approval path)');
  assert.match(flow, /mfl_text|mflText/, 'the .mfl text is shown before saving');
});

test('T5 activation sends nothing, saves nothing, mints no approval', async () => {
  const [flow, slot, hook] = await Promise.all([
    read('../src/shell/FluidTableFlow.tsx'),
    read('../src/shell/StepBarSlot.tsx'),
    read('../src/shell/useWorkbenchCommands.ts'),
  ]);
  for (const [name, source] of [['flow', flow], ['banner', slot]]) {
    assert.doesNotMatch(source, /\/api\/chat/, `${name} never posts to chat on its own`);
    assert.doesNotMatch(source, /run_execute|executeApproval/, `${name} never runs or approves`);
    assert.doesNotMatch(source, /approval_required/, `${name} mints no approval`);
  }
  assert.doesNotMatch(flow, /launch_multiflash|open-multiflash.*approved:\s*true/i, 'import is never launched without the explicit click');
});

test('T5 manual steps stay generic until the menu path is confirmed', async () => {
  const flow = await read('../src/shell/FluidTableFlow.tsx');
  assert.match(flow, /fluid\.manualSteps/, 'manual steps read through the dictionary');
  assert.equal(translate('ko', 'fluid.manualSteps'), 'Multiflash에서 OLGA 표 만들기를 실행하세요', 'generic manual instruction');
  assert.doesNotMatch(flow, /Run Script|File →|파일 → 실행/, 'no unverified menu path');
  assert.doesNotMatch(translate('ko', 'fluid.manualSteps'), /Run Script|File →|파일 → 실행/, 'no unverified menu path in copy');
});

test('M4/T5 i18n: tabbanner.* + fluid.* resolve in ko+en, en carries no Hangul', async () => {
  const keys = [
    'tabbanner.need', 'tabbanner.how', 'tabbanner.create',
    'tabbanner.openWorkspace', 'tabbanner.preview', 'tabbanner.previewHint',
  ];
  for (const key of keys) {
    assert.notEqual(translate('ko', key), key, `${key} resolves in ko`);
    assert.notEqual(translate('en', key), key, `${key} resolves in en`);
    assert.doesNotMatch(translate('en', key), /[가-힣]/, `${key} carries no Hangul in en`);
  }
  assert.equal(translate('ko', 'tabbanner.need'), '이 사례에는 유체 표(.tab)가 필요합니다');
  assert.equal(translate('en', 'tabbanner.need'), 'This case needs a fluid table (.tab)');
  assert.equal(translate('ko', 'tabbanner.create'), '유체 표 만들기');
  assert.equal(translate('en', 'tabbanner.create'), 'Create fluid table');
  const fluidKeys = [
    'fluid.title', 'fluid.label', 'fluid.model', 'fluid.components', 'fluid.addComponent',
    'fluid.name', 'fluid.fraction', 'fluid.sum', 'fluid.temperatures', 'fluid.pressures',
    'fluid.previewAction', 'fluid.previewTitle', 'fluid.saveAction', 'fluid.openAction',
    'fluid.ranAction', 'fluid.pickupTitle', 'fluid.linkAction', 'fluid.closeAction',
    'fluid.manualSteps', 'fluid.emptyHint',
  ];
  for (const key of fluidKeys) {
    assert.notEqual(translate('ko', key), key, `${key} resolves in ko`);
    assert.notEqual(translate('en', key), key, `${key} resolves in en`);
    assert.doesNotMatch(translate('en', key), /[가-힣]/, `${key} carries no Hangul in en`);
  }
});
