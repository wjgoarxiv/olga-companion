import assert from 'node:assert/strict';
import test from 'node:test';

import { ko } from '../src/i18n/ko.ts';
import { en } from '../src/i18n/en.ts';
import { approvalCardRenderer } from './helpers/render-approval-card.mjs';

const render = await approvalCardRenderer();
const req = (name, args = {}) => ({ name, call_id: 'c', pending_id: 'p', args, display: {} });

// "Publish" is not the user's word and "Approve and cancel" reads as cancelling the approval.
test('save and stop buttons say the effect, in both languages', () => {
  const publish = req('case_publish', { transaction_id: 't', compiled_hash: 'h', destination_rel: 'a/b.genkey', context_generation: 1 });
  assert.ok(render('ko', publish).includes('>승인하고 사례 저장<'));
  assert.ok(render('en', publish).includes('>Approve and save the case<'));
  for (const name of ['run_cancel', 'sweep_cancel']) {
    assert.ok(render('ko', req(name)).includes('>승인하고 중단<'), `${name} ko`);
    assert.ok(render('en', req(name)).includes('>Approve and stop<'), `${name} en`);
  }
  assert.notEqual(ko['approval.approveCancel'], en['approval.approveCancel']);
  assert.doesNotMatch(ko['approval.approvePublish'], /게시/);
});

test('every approval kind puts the primary approve first and the reject second', () => {
  for (const name of ['case_publish', 'run_execute', 'sweep_execute', 'run_cancel', 'multiflash_open', 'genkey_save']) {
    for (const locale of ['ko', 'en']) {
      const html = render(locale, req(name));
      const approve = html.indexOf('ui-button-primary approve');
      const reject = html.indexOf('ui-button-secondary reject');
      assert.ok(approve > 0 && reject > approve, `${name} ${locale}: approve before reject`);
      assert.equal((html.match(/ui-button-primary/g) ?? []).length, 1, `${name} ${locale}: one primary button`);
    }
  }
});
