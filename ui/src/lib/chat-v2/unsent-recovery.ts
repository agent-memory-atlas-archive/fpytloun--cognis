// Per-conversation composer draft persistence for compact chats, and recovery
// of messages that were queued but will never be sent (permanent rejection,
// or an outbox copy that would not survive a reload) when the view that
// queued them no longer shows their conversation.
//
// Draft text lives under `cognis:chat-v2-draft:<id>` (shared with the main
// chat page); draft attachments under `cognis:chat-v2-draft-attachments:<id>`.
// Attachment refs are kept as-is, including local placeholders: their files
// are persisted by attachmentUploads and resolved (uploaded) on send.

import { mergeFailedSendIntoDraft } from './outbox-retry';
import type { OutboxEntry } from './outbox';
import type { AttachmentRef } from '$lib/types/api';
import type { DocumentDrafts } from '$lib/offline/document-drafts';

const draftKey = (conversationId: string) => `cognis:chat-v2-draft:${conversationId}`;
const attachmentsKey = (conversationId: string) => `cognis:chat-v2-draft-attachments:${conversationId}`;

/**
 * Composer input that reproduces an outbox entry. Entries store normalized
 * content, so a one-shot mode message ("/plan /yolo on" → "/yolo on" in plan
 * mode) gets its directive back; restoring the bare content could turn it
 * into a command on the next Send.
 */
export function composerTextForEntry(entry: Pick<OutboxEntry, 'content' | 'chat_mode'>): string {
  const content = entry.content ?? '';
  if (!entry.chat_mode || !content.trim()) return content;
  return `/${entry.chat_mode} ${content}`;
}

/** Draft attachments stored for `conversationId` (not removed). */
export function readDraftAttachments(conversationId: string, drafts: DocumentDrafts): AttachmentRef[] {
  if (typeof localStorage === 'undefined') return [];
  try {
    const raw = drafts.read(attachmentsKey(conversationId));
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter((item): item is AttachmentRef => typeof item?.artifact_id === 'string')
      : [];
  } catch {
    return [];
  }
}

/** Attachment lists of every stored composer draft (for blob pruning). */
export function allDraftAttachmentLists(drafts: DocumentDrafts): AttachmentRef[][] {
  if (typeof localStorage === 'undefined') return [];
  const prefix = 'cognis:chat-v2-draft-attachments:';
  const lists: AttachmentRef[][] = [];
  try {
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      // Legacy keys have no provable author; never use them for restore/cleanup.
      if (key?.startsWith(prefix) && key.includes(':account-v2:') && !key.includes(':retained:')) {
        const id = key.slice(prefix.length).split(':account-v2:')[0];
        lists.push(readDraftAttachments(id, drafts));
      }
    }
  } catch {
    // Storage unavailable.
  }
  return lists;
}

/** Replace the draft attachments of `conversationId` (empty removes them). */
export function writeDraftAttachments(conversationId: string, attachments: AttachmentRef[], drafts: DocumentDrafts): Promise<void> {
  if (typeof localStorage === 'undefined') return Promise.resolve();
  try {
    return drafts.write(attachmentsKey(conversationId),
      attachments.length ? JSON.stringify(attachments) : null);
  } catch {
    return Promise.resolve();
  }
}

/** Add an unsent message to `conversationId`'s stored draft (text + files). */
export function stashUnsentMessage(
  conversationId: string,
  text: string,
  attachments: AttachmentRef[] = [],
  drafts: DocumentDrafts,
): Promise<void> {
  if (typeof localStorage === 'undefined') return Promise.resolve();
  const pending: Promise<unknown>[] = [];
  try {
    if (text.trim()) {
      const key = draftKey(conversationId);
      pending.push(drafts.write(key, mergeFailedSendIntoDraft(text, drafts.read(key) ?? '')));
    }
  } catch {
    // Storage full or unavailable: nothing else can hold it.
  }
  if (attachments.length === 0) return Promise.all(pending).then(() => undefined);
  const existing = readDraftAttachments(conversationId, drafts);
  const present = new Set(existing.map((item) => item.artifact_id));
  pending.push(writeDraftAttachments(conversationId, [
    ...attachments.filter((item) => !present.has(item.artifact_id)),
    ...existing,
  ], drafts));
  return Promise.all(pending).then(() => undefined);
}
