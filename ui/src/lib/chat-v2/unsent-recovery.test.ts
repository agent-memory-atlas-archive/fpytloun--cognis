import { beforeEach, describe, expect, it } from 'vitest';
import 'fake-indexeddb/auto';

import { normalizeChatComposerInput } from './composer-dispatch';
import {
  composerTextForEntry,
  readDraftAttachments,
  stashUnsentMessage,
  writeDraftAttachments,
} from './unsent-recovery';
import type { AttachmentRef } from '$lib/types/api';
import { DocumentDrafts } from '$lib/offline/document-drafts';
import { documentCoordination } from '$lib/document-coordination';

const uploaded = { artifact_id: 'art_1', kind: 'image', mime_type: 'image/png', filename: 'a.png', size_bytes: 1 } as AttachmentRef;
const local = { artifact_id: 'local:x', local_id: 'x', kind: 'image', mime_type: 'image/png', filename: 'b.png', size_bytes: 1 } as AttachmentRef;

describe('unsent message recovery', () => {
  let drafts: DocumentDrafts;
  beforeEach(async () => {
    localStorage.clear();
    await documentCoordination().beginLogin();
    await documentCoordination().verified('recovery@cognis.test');
    drafts = new DocumentDrafts();
  });

  it('restores the mode directive so a one-shot message never turns into a command', () => {
    const normalized = normalizeChatComposerInput({ content: '/plan /yolo on' });
    expect(normalized).toMatchObject({ kind: 'message', content: '/yolo on', chatMode: 'plan' });
    const text = composerTextForEntry({ content: normalized.content, chat_mode: normalized.chatMode });
    expect(text).toBe('/plan /yolo on');
    expect(normalizeChatComposerInput({ content: text })).toMatchObject({ kind: 'message', content: '/yolo on', chatMode: 'plan' });
    expect(composerTextForEntry({ content: 'hello', chat_mode: undefined })).toBe('hello');
  });

  it('stashes owned text/files while leaving unowned legacy bytes untouched', async () => {
    const key = 'cognis:chat-v2-draft:c1';
    localStorage.setItem(key, 'unverified legacy');
    await drafts.write(key, 'typed later');
    await stashUnsentMessage('c1', 'failed text', [uploaded, local], drafts);
    expect(drafts.read(key)).toContain('failed text');
    expect(drafts.read(key)).toContain('typed later');
    expect(localStorage.getItem(key)).toBe('unverified legacy');
    expect(readDraftAttachments('c1', drafts)).toEqual([uploaded, local]);
  });

  it('lists every draft attachment set so pruning keeps their files', async () => {
    const { allDraftAttachmentLists } = await import('./unsent-recovery');
    await writeDraftAttachments('c3', [local], drafts);
    await writeDraftAttachments('c4', [uploaded], drafts);
    localStorage.setItem('unrelated', '1');
    expect(allDraftAttachmentLists(drafts).flat()).toEqual(expect.arrayContaining([local, uploaded]));
  });

  it('keeps draft files across repeated reads until the draft changes', async () => {
    await stashUnsentMessage('c2', '', [uploaded], drafts);
    await stashUnsentMessage('c2', '', [uploaded], drafts);
    expect(readDraftAttachments('c2', drafts)).toEqual([uploaded]);
    expect(readDraftAttachments('c2', drafts)).toEqual([uploaded]);
    await writeDraftAttachments('c2', [], drafts);
    expect(readDraftAttachments('c2', drafts)).toEqual([]);
  });
});
