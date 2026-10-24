import { beforeEach, expect, it } from 'vitest';
import 'fake-indexeddb/auto';
import { DocumentDrafts, type CompositeInput } from '$lib/offline/document-drafts';
import type { AttachmentRef } from '$lib/types/api';
import { documentCoordination } from '$lib/document-coordination';
import { hydrateComposer, selectLegacyInput, canSelectRecovery } from './composer-hydration';
import { ComposerSubmission } from './composer-submission';
import { createIndexedDbChatV2Outbox } from './outbox';

beforeEach(async () => {
  localStorage.clear();
  await documentCoordination().initialize();
  await documentCoordination().invalidate(false);
  await documentCoordination().verified('hydrate@cognis.test');
});
const refs: AttachmentRef[] = [{ artifact_id: 'local:hydration-image', local_id: 'hydration-image',
  filename: 'synthetic.png', kind: 'image', mime_type: 'image/png', size_bytes: 1 }];

for (const mode of [null, 'default', 'plan', 'build'] as const) {
  for (const from of ['cognis-chat-draft:', 'cognis:chat-v2-draft:']) {
    it(`hydrates the entire ${mode} intent from ${from} without consulting current mode`, async () => {
      const drafts = new DocumentDrafts();
      const input: CompositeInput = { text: 'saved input', attachments: refs, chat_mode: mode, input_revision: crypto.randomUUID() };
      drafts.readComposite(`${from}conversation`);
      await drafts.writeComposite(`${from}conversation`, input);
      const result = hydrateComposer(new DocumentDrafts(), 'conversation');
      expect(result.input).toEqual(input);
      expect(result.legacy).toEqual([]);
      const lease = documentCoordination().capture(), outbox = createIndexedDbChatV2Outbox();
      const makeSubmission = (draftKey: string, hydrated: CompositeInput) => new ComposerSubmission({
        ...hydrated, draftKey, conversationId: 'conversation', generation: 1, revision: 1,
      }, {
        client_txn_id: crypto.randomUUID(), client_message_id: crypto.randomUUID(),
        conversation_id: 'conversation', content: hydrated.text, attachments: hydrated.attachments,
        chat_mode: hydrated.chat_mode, status: 'pending',
        created_at: '2026-10-20T00:00:00Z', updated_at: '2026-10-20T00:00:00Z',
      }, lease, { prepare: async () => {} });
      const original = await makeSubmission(`${from}conversation`, input).prepare(drafts, outbox);
      const opposite = from === 'cognis-chat-draft:' ? 'cognis:chat-v2-draft:' : 'cognis-chat-draft:';
      const reopened = new DocumentDrafts(), recovered = hydrateComposer(reopened, 'conversation');
      const retried = await makeSubmission(`${opposite}conversation`, recovered.input).prepare(reopened, outbox);
      expect(retried).toEqual(original);
      expect(retried.chat_mode).toBe(mode);
    });
  }
}
for (const key of ['cognis-chat-draft:', 'cognis:chat-v2-draft:']) {
  it(`discovers opposite legacy ${key} without initializing a composite`, async () => {
    const drafts = new DocumentDrafts();
    drafts.read(`${key}conversation`);
    await drafts.write(`${key}conversation`, 'legacy');
    const result = hydrateComposer(drafts, 'conversation');
    expect(result.legacy).toHaveLength(1);
    expect(result.legacy[0].input.text).toBe('legacy');
    expect(drafts.readComposite('cognis-chat-draft:conversation')).toBeNull();
  });
}
it('preserves both legacy inputs without selecting, merging or deduplicating them', async () => {
  const drafts = new DocumentDrafts();
  for (const key of ['cognis-chat-draft:conversation', 'cognis:chat-v2-draft:conversation']) {
    drafts.read(key); await drafts.write(key, 'same text, distinct historical intents');
  }
  const result = hydrateComposer(drafts, 'conversation');
  expect(result.legacy).toHaveLength(2);
  expect(result.input.text).toBe('');
  const chosen = selectLegacyInput(result.legacy[1]);
  expect(chosen.input_revision).toBeTruthy();
  expect(chosen.text).toBe(result.legacy[1].input.text);
  expect(hydrateComposer(drafts, 'conversation').legacy).toHaveLength(2);
  expect(selectLegacyInput(result.legacy[0], 'default').chat_mode).toBe('default');
  expect(selectLegacyInput(result.legacy[0], null).chat_mode).toBeNull();
});
it('fails closed on malformed legacy attachments and does not hide them', async () => {
  const drafts = new DocumentDrafts(), key = 'cognis:chat-v2-draft-attachments:conversation';
  drafts.read(key); await drafts.write(key, '{broken');
  expect(() => hydrateComposer(drafts, 'conversation')).toThrow();
  expect(drafts.readComposite('cognis-chat-draft:conversation')).toBeNull();
  expect(drafts.read(key)).toBe('{broken');
});
it('returns an empty intent only when no recovery exists, and never replaces newer canonical input', async () => {
  const drafts = new DocumentDrafts();
  expect(hydrateComposer(drafts, 'conversation').legacy).toEqual([]);
  const current = { text: 'newer', attachments: refs, chat_mode: 'build' as const, input_revision: crypto.randomUUID() };
  await drafts.writeComposite('cognis-chat-draft:conversation', current);
  drafts.read('cognis:chat-v2-draft:conversation');
  await drafts.write('cognis:chat-v2-draft:conversation', 'old');
  expect(hydrateComposer(drafts, 'conversation').input).toEqual(current);
});

it('fences captured selection by view identity, generation, closure and owner revocation', async () => {
  const candidate = { source: 'full' as const, input: { text: 'A', attachments: [], chat_mode: null } };
  const owner = documentCoordination();
  const scope = { conversationId: 'A', generation: 1, lease: owner.capture(), candidates: [candidate] };
  expect(canSelectRecovery(scope, scope, 'A', 1, true, candidate)).toBe(true);
  expect(canSelectRecovery(scope, null, 'B', 2, true, candidate)).toBe(false);
  expect(canSelectRecovery(scope, scope, 'A', 2, true, candidate)).toBe(false);
  expect(canSelectRecovery(scope, scope, 'A', 1, false, candidate)).toBe(false);
  await owner.invalidate(false);
  expect(canSelectRecovery(scope, scope, 'A', 1, true, candidate)).toBe(false);
});
