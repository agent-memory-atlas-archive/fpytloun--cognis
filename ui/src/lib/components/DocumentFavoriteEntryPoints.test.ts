import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Writable } from 'svelte/store';
import { auth } from '$lib/stores/auth';
import type { Deliverable, StepRun } from '$lib/types/api';
import AssistantDeliverableBlock from './AssistantDeliverableBlock.svelte';
import MessageAttachments from './MessageAttachments.svelte';
import AttachmentPreviewModal from './AttachmentPreviewModal.svelte';
import TaskStepOutcomeEpilogue from './tasks/TaskStepOutcomeEpilogue.svelte';
import './rich/RichDeliverable.svelte';

const mocks = vi.hoisted(() => ({ item: vi.fn(), favorite: vi.fn(), step: vi.fn() }));
vi.mock('$lib/stores/auth', async () => {
  const { writable } = await import('svelte/store');
  return { auth: writable({ user: null }) };
});
vi.mock('$lib/api/client', () => ({
  api: {
    library: { item: mocks.item, favorite: mocks.favorite },
    deliverables: { getForStepRun: mocks.step },
    artifacts: {
      signedUrl: vi.fn().mockResolvedValue({ url: '/signed-file' }),
      textPreview: vi.fn().mockResolvedValue({ content: '# Report', truncated: false }),
    },
  },
}));
const deliverable = {
  deliverable_id: 'dlv_favorite_report', step_run_id: 'step_favorite_report', title: 'Favorite report',
  format: 'markdown', content: '# Report\n\nVerified content.', rich_payload: null,
  status: 'delivered', version: 1, outputs: {}, validation_warnings: [],
} as unknown as Deliverable;
let account = 0;
describe('Favorites at task and chat integration boundaries', () => {
  beforeEach(() => {
    (auth as unknown as Writable<{ user: { email: string } }>).set({ user: { email: `reader-${++account}@test.local` } });
    mocks.item.mockImplementation(async (kind: string, id: string) => ({ kind, id, lineage_id: id, is_favorite: false }));
    mocks.favorite.mockImplementation(async (kind: string, id: string, favorite: boolean) => ({ kind, id, lineage_id: id, is_favorite: favorite }));
    mocks.step.mockResolvedValue(deliverable);
    mocks.favorite.mockClear();
    mocks.item.mockClear();
  });
  async function star(kind: string, id: string) {
    const button = await screen.findByRole('button', { name: 'Add to favorites' });
    await waitFor(() => expect(button).toBeEnabled());
    await fireEvent.click(button);
    await waitFor(() => expect(mocks.favorite).toHaveBeenCalledWith(kind, id, true));
    expect(await screen.findByRole('button', { name: 'Remove from favorites' })).toHaveAttribute('aria-pressed', 'true');
  }
  it('stars a chat deliverable through its shared preview header', async () => {
    render(AssistantDeliverableBlock, {
      item: { id: deliverable.deliverable_id, kind: 'assistant_deliverable', deliverableId: deliverable.deliverable_id, format: deliverable.format },
      loadDeliverable: async () => deliverable,
    });
    await star('deliverable', deliverable.deliverable_id);
  });
  it('stars a task outcome through the step-scoped loader', async () => {
    render(TaskStepOutcomeEpilogue, {
      stepRun: { step_run_id: 'step_favorite_report', status: 'completed', deliverables: [deliverable] } as StepRun,
    });
    await star('deliverable', deliverable.deliverable_id);
    expect(mocks.step).toHaveBeenCalledWith('step_favorite_report', deliverable.deliverable_id);
  });
  it('keeps favorite controls out of message file attachments', () => {
    render(MessageAttachments, { attachments: [{
      artifact_id: 'art_favorite_chat', filename: 'report.md', mime_type: 'text/markdown', size_bytes: 42, kind: 'file',
    }] });
    expect(screen.queryByRole('button', { name: 'Add to favorites' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Preview report.md' })).toBeVisible();
    expect(mocks.item).not.toHaveBeenCalled();
  });
  it('keeps favorite controls out of image thumbnails', () => {
    render(MessageAttachments, { attachments: [{
      artifact_id: 'art_favorite_image', filename: 'screenshot.png', mime_type: 'image/png',
      size_bytes: 42, kind: 'image', url: '/screenshot.png',
    }] });
    expect(screen.queryByRole('button', { name: 'Add to favorites' })).toBeNull();
    expect(screen.getByRole('button', { name: 'View screenshot.png' })).toBeVisible();
    expect(mocks.item).not.toHaveBeenCalled();
  });
  it('still stars a chat attachment from the opened preview', async () => {
    render(AttachmentPreviewModal, {
      attachment: { artifact_id: 'art_favorite_chat', filename: 'report.md', mime_type: 'text/markdown', kind: 'file', size_bytes: 42 },
      kind: 'markdown', onClose: vi.fn(), resolveDownloadUrl: async () => '/signed-file',
    });
    await star('artifact', 'art_favorite_chat');
  });
  it('still stars an image after opening its lightbox', async () => {
    render(MessageAttachments, { attachments: [{
      artifact_id: 'art_favorite_image', filename: 'screenshot.png', mime_type: 'image/png',
      size_bytes: 42, kind: 'image', url: '/screenshot.png',
    }] });
    expect(screen.queryByRole('button', { name: 'Add to favorites' })).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'View screenshot.png' }));
    await star('artifact', 'art_favorite_image');
  });
  it('does not offer favorites for an upload that is still local', () => {
    render(MessageAttachments, { attachments: [{
      artifact_id: 'local:upload_favorite', local_id: 'upload_favorite', upload_state: 'uploading',
      filename: 'report.md', mime_type: 'text/markdown', size_bytes: 42, kind: 'file',
    }] });
    expect(screen.queryByRole('button', { name: 'Add to favorites' })).toBeNull();
  });
});
