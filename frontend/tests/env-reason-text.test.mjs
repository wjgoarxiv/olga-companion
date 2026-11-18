// N7 (D2): system status reasons read in the UI language; OPC conditions are named in words.
import assert from 'node:assert/strict';
import test from 'node:test';
import { reviewNotesRenderer } from './helpers/render-review-notes.mjs';

const r = await reviewNotesRenderer();
const opc = {
  enabled: false,
  reason: 'Gated until verified: opc_dependencies, windows_dcom, olga_server_mode, read_write_separation, explicit_write_approval.',
  reason_code: 'opc_gated',
  reason_params: { conditions: ['opc_dependencies', 'windows_dcom', 'olga_server_mode', 'read_write_separation', 'explicit_write_approval'] },
};

test('the OPC row reads in Korean with no raw identifiers (D2)', () => {
  const text = r.envReason('ko', opc);
  assert.equal(text, '다음을 확인할 때까지 꺼져 있어요: OPC 라이브러리, Windows DCOM 권한, 실행 중인 OLGA 서버 모드 시뮬레이션, 읽기·쓰기 항목 분리, 쓰기마다 승인.');
  assert.doesNotMatch(text, /[a-z]+_[a-z]+/);
});

test('the OLGA row names only the program file, not the folder', () => {
  const cap = { enabled: true, reason: 'x', reason_code: 'olga_detected', reason_params: { exe: 'C:\\Program Files\\Schlumberger\\OLGA 2022.1.0\\OlgaExecutables\\OLGA-2022.1.0.exe', version: '2022.1.0' } };
  assert.equal(r.envReason('en', cap), 'OLGA 2022.1.0 found (OLGA-2022.1.0.exe). Each run still checks the case and asks for your approval.');
});

test('every code the server sends has English and Korean words', () => {
  const codes = ['toolkit_found', 'toolkit_missing', 'fluid_toolkit_found', 'fluid_toolkit_missing', 'multiflash_ready', 'multiflash_needs_windows',
    'multiflash_not_found', 'olga_detected', 'olga_not_found', 'olga_unsupported_native', 'broker_unavailable', 'result_parser_ready',
    'result_toolkit_missing', 'result_fixture_missing', 'result_parser_failed', 'renderer_ready', 'renderer_missing', 'renderer_failed',
    'opc_ready', 'opc_gated', 'diagnostics_found', 'diagnostics_missing'];
  for (const code of codes) {
    for (const locale of ['en', 'ko']) {
      const params = { missing: ['checked-in broker source'], exe: 'C:\\x\\OLGA-1.exe', version: '2022.1.0', dependency: 'matplotlib', script: 'diag.py', conditions: ['windows_dcom'] };
      const text = r.envReason(locale, { enabled: true, reason: 'SERVER', reason_code: code, reason_params: params });
      assert.notEqual(text, 'SERVER', `${locale} ${code}`);
      assert.doesNotMatch(text, /env\.reason|\{[a-z_]+\}/, `${locale} ${code}`);
    }
  }
});

test('an unknown code or no code keeps the server words', () => {
  assert.equal(r.envReason('ko', { enabled: true, reason: 'Server words.', reason_code: 'new_thing' }), 'Server words.');
  assert.equal(r.envReason('ko', { enabled: true, reason: 'Server words.' }), 'Server words.');
});

test('the shown reason carries no folder path, also on hover (review)', () => {
  const cap = { enabled: true, reason: 'OLGA executable detected via standard_glob: C:\\Users\\someone\\OLGA 2022.1.0\\OlgaExecutables\\OLGA-2022.1.0.exe', reason_code: 'olga_detected', reason_params: { exe: 'C:\\Users\\someone\\OLGA 2022.1.0\\OlgaExecutables\\OLGA-2022.1.0.exe', version: '2022.1.0' } };
  const html = r.renderCapabilityReason('ko', cap);
  assert.match(html, /OLGA-2022\.1\.0\.exe/);
  assert.doesNotMatch(html, /someone|Users|title=/);
  assert.match(html, /^<small class="capability-reason">OLGA 2022\.1\.0을\(를\) 찾았어요/);
});
