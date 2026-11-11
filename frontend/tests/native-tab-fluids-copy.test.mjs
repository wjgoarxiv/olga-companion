import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { en } from '../src/i18n/en.ts';
import { ko } from '../src/i18n/ko.ts';
import { approvalCardRenderer } from './helpers/render-approval-card.mjs';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const render = await approvalCardRenderer();

const RELEASE_EN_EXPLAINER = 'A PVT table (.tab) is made by a fluid property program (e.g. Multiflash, PVTsim). The app does not create fluid data.';
const RELEASE_KO_EXPLAINER = 'PVT 표(.tab)는 유체 물성 프로그램(예: Multiflash, PVTsim)에서 만든 파일입니다. 앱은 유체 데이터를 만들지 않습니다.';
const RELEASE_EN_SUBTITLE = 'Enter the composition to preview an .mfl draft, then build the table in Multiflash';
const RELEASE_KO_SUBTITLE = '조성을 입력하면 .mfl 초안을 미리보고, Multiflash에서 표를 만듭니다';
const NATIVE_MARK = /AI assistant can generate an independent table in the app/;

test('release fluid copy stays in both languages', () => {
  assert.equal(en['intake.tabExplainer'], RELEASE_EN_EXPLAINER);
  assert.equal(ko['intake.tabExplainer'], RELEASE_KO_EXPLAINER);
  assert.equal(en['fluid.subtitle'], RELEASE_EN_SUBTITLE);
  assert.equal(ko['fluid.subtitle'], RELEASE_KO_SUBTITLE);
});

test('native fluid copy names the in-app assistant in both languages', () => {
  assert.match(en['intake.tabExplainer.native'], NATIVE_MARK);
  assert.match(en['fluid.subtitle.native'], NATIVE_MARK);
  assert.match(ko['intake.tabExplainer.native'], /AI 어시스턴트/);
  assert.match(ko['intake.tabExplainer.native'], /독립/);
  assert.match(ko['fluid.subtitle.native'], /AI 어시스턴트/);
  assert.match(ko['fluid.subtitle.native'], /독립/);
  assert.doesNotMatch(en['intake.tabExplainer.native'], /does not create fluid data/);
  assert.doesNotMatch(ko['intake.tabExplainer.native'], /유체 데이터를 만들지 않습니다/);
});

test('the panels switch copy when the native generator is available', async () => {
  const [checklist, flow, app, slot, stepBar, guide] = await Promise.all([
    read('../src/NewCaseChecklist.tsx'),
    read('../src/shell/FluidTableFlow.tsx'),
    read('../src/App.tsx'),
    read('../src/shell/StepBarSlot.tsx'),
    read('../src/shell/StepBar.tsx'),
    read('../src/SimulationGuide.tsx'),
  ]);
  assert.match(checklist, /nativeTab/);
  assert.match(checklist, /intake\.tabExplainer\.native/);
  assert.match(flow, /nativeTab/);
  assert.match(flow, /fluid\.subtitle\.native/);
  assert.match(app, /native_tab/);
  for (const source of [slot, stepBar, guide]) {
    assert.match(source, /nativeTab/);
  }
});

test('the approval card shows the companion mfl file in English and Korean', () => {
  const request = {
    name: 'fluids_generate_tab',
    call_id: 'call_tab',
    pending_id: 'pending_tab',
    args: {},
    display: {
      fields: [
        { key: 'file', value: 'syn_co2.tab' },
        { key: 'mfl_file', value: 'syn_co2.mfl' },
      ],
    },
  };
  const english = render('en', request);
  const korean = render('ko', request);
  assert.match(english, /syn_co2\.mfl/);
  assert.match(korean, /syn_co2\.mfl/);
  assert.match(english, /<dt>Multiflash draft \(\.mfl\)<\/dt>/);
  assert.match(korean, /<dt>Multiflash 초안 \(\.mfl\)<\/dt>/);
});
