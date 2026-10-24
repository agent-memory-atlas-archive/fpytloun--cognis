import type { AttachmentRef } from '$lib/types/api';
import type { ChatMode } from './types';
import { snapshotPersistedMetadata } from './persisted-metadata';

export interface SubmissionInput {
  text: string;
  attachments: AttachmentRef[];
  chat_mode: ChatMode | null;
}
export interface SubmissionBinding {
  version: 1;
  draft_key: string;
  input_revision: string;
  input: SubmissionInput;
}
export function normalizeSubmissionInput(input: SubmissionInput): SubmissionInput {
  return snapshotPersistedMetadata({
    text: input.text,
    chat_mode: input.chat_mode,
    attachments: input.attachments.map(({ upload_progress, upload_state, upload_error, ...ref }) => ref),
  });
}
function ordered(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(ordered);
  if (value && typeof value === 'object') return Object.fromEntries(
    Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => [k, ordered(v)]));
  return value;
}
export function sameSubmissionInput(a: SubmissionInput, b: SubmissionInput): boolean {
  return JSON.stringify(ordered(normalizeSubmissionInput(a))) === JSON.stringify(ordered(normalizeSubmissionInput(b)));
}
