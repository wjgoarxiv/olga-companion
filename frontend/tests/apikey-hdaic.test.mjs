// HD AIC is offered as a ready-made API-key connection with a model list.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { HD_AIC_PRESET } from '../src/apiKeyPresets.mjs';

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');

test('the HD AIC preset is an https OpenAI chat endpoint', () => {
  assert.equal(HD_AIC_PRESET.protocol, 'openai-chat');
  assert.match(HD_AIC_PRESET.baseUrl, /^https:\/\/api\.model\.hd-aic\.com\/v1$/);
  assert.equal(HD_AIC_PRESET.label, 'HD AIC');
});

test('settings offer the preset and a model list, in both languages', () => {
  const ui = read('../src/ApiKeyConnections.tsx');
  assert.match(ui, /HD_AIC_PRESET/);
  assert.match(ui, /listApiKeyModels/);
  assert.match(read('../src/apiKeyApi.ts'), /\/api\/providers\/apikey\/models/);
  for (const key of ['apikey.hdaicPreset', 'apikey.hdaicHint', 'apikey.modelsLoad', 'apikey.modelsEmpty', 'apikey.modelsFailed']) {
    assert.ok(read('../src/i18n/ko.ts').includes(`'${key}'`), `ko ${key}`);
    assert.ok(read('../src/i18n/en.ts').includes(`'${key}'`), `en ${key}`);
  }
});
