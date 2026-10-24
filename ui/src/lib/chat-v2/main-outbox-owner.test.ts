import { describe, expect, it } from 'vitest';
import source from '../../routes/(app)/chat/[conversationId]/+page.svelte?raw';

describe('main composer canonical admission wiring', () => {
  it('routes direct admission and retry draining through shared owners', () => {
    expect(source).not.toContain('chatV2Api.sendMessage(');
    expect(source).not.toContain('chatV2Outbox.delete(');
    expect(source).toContain('drainConversationOutbox({');
    expect(source).toContain('}, { outbox: chatV2Outbox });');
    expect(source).not.toContain('sending online without durable retry');
    expect(source).toContain('projectAdmissionFailure(chatV2Outbox');
    expect(source).not.toMatch(/chatV2Outbox\.update\([^;]+status:\s*'failed'/s);
    const prepare = source.indexOf('await submission.prepare(composerDrafts, chatV2Outbox,');
    const clear = source.indexOf("composer = '';", prepare);
    expect(prepare).toBeGreaterThan(0);
    expect(clear).toBeGreaterThan(prepare);
    expect(source.slice(prepare, clear)).toContain('submission?.matchesInput(composerView())');
    expect(source.slice(prepare, clear)).toContain('flushPendingDraft()');
    expect(source.slice(prepare, clear)).toContain('catch (persistenceError)');
    expect(source.slice(prepare, clear)).toContain('await submission.consume(composerDrafts, composerView');
    expect(source).not.toContain('clearDraft(');
    const pinDirect = source.indexOf('await composerDrafts.persistComposite(submittedView.draftKey!, submittedView)');
    const consumeDirect = source.indexOf('await composerDrafts.consumeComposite(pinned,', pinDirect);
    const clearDirect = source.indexOf("composer = '';", consumeDirect);
    expect(pinDirect).toBeGreaterThan(clear);
    expect(consumeDirect).toBeGreaterThan(pinDirect);
    expect(clearDirect).toBeGreaterThan(consumeDirect);
    expect(source.slice(pinDirect, clearDirect)).toContain(
      '() => canProjectSubmission() && composerInputRevision === submittedView.input_revision',
    );
    expect(source.slice(consumeDirect, clearDirect)).toContain(
      'if (consumedDirect && canProjectSubmission() && composerInputRevision === submittedView.input_revision)',
    );
    expect(source).toContain('submission.canResize(composerView())');
    expect(source).toContain('canProjectSubmission() && chatV2OwnsActiveConversation(sendConversationId)');
  });
});
