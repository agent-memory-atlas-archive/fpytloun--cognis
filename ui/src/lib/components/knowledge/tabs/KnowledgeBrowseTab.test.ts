import { fireEvent, render, screen } from '@testing-library/svelte';
import { flushSync } from 'svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { KnowledgebaseDocumentModel, KnowledgebaseModel } from '$lib/types/api';
import { resolveDocumentContent } from '$lib/knowledge/content';
import KnowledgeBrowseTab from './KnowledgeBrowseTab.svelte';

vi.mock('$lib/knowledge/content', () => ({
  resolveDocumentContent: vi.fn().mockResolvedValue(null),
  resolveDownloadUrl: vi.fn().mockResolvedValue(null)
}));

const kb: KnowledgebaseModel = {
  knowledgebase_id: 'kb_1', owner_email: 'owner@example.com', access_level: 'owner',
  name: 'Product docs', description: null, status: 'active', metadata_schema: {},
  settings: {}, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  archived_at: null
};

function document(source_path: string | null = null): KnowledgebaseDocumentModel {
  return {
    doc_id: 'kba_1', knowledgebase_id: kb.knowledgebase_id, artifact_id: null,
    display_name: 'image.png', source_path, mime_type: 'image/png', size_bytes: 100,
    status: 'failed', chunk_count: 0, metadata: {}, last_job_id: null,
    last_error: 'Extraction failed', attached_at: null, indexed_at: null
  };
}

describe('KnowledgeBrowseTab expansion', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }));
  });

  it.each([null, 'image.png'])('keeps a flat failed-document list interactive (%s)', async (path) => {
    const doc = document(path);
    render(KnowledgeBrowseTab, { kb, documents: [doc] });
    // Flush effects explicitly to catch the previous empty-set feedback loop.
    flushSync();
    await fireEvent.click(screen.getByRole('treeitem', { name: 'image.png' }));
    expect(resolveDocumentContent).toHaveBeenCalledWith(kb.knowledgebase_id, doc, expect.any(AbortSignal));
    await fireEvent.input(screen.getByTestId('knowledge-tree-filter'), { target: { value: 'missing' } });
    expect(screen.getByText('No documents match "missing".')).toBeInTheDocument();
  });

  it('does not reopen the last collapsed folder, including after a document refresh', async () => {
    const doc = document('images/image.png');
    const view = render(KnowledgeBrowseTab, { kb, documents: [doc] });
    flushSync();
    const folder = screen.getByRole('treeitem', { name: 'images' });
    expect(folder).toHaveAttribute('aria-expanded', 'true');
    await fireEvent.click(folder);
    expect(folder).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('treeitem', { name: 'image.png' })).not.toBeInTheDocument();
    await view.rerender({ kb, documents: [{ ...doc }] });
    expect(folder).toHaveAttribute('aria-expanded', 'false');
    await fireEvent.click(folder);
    expect(screen.getByRole('treeitem', { name: 'image.png' })).toBeInTheDocument();
  });

  it('initializes folders when documents arrive after an empty initial render', async () => {
    const view = render(KnowledgeBrowseTab, { kb, documents: [] });
    flushSync();
    await view.rerender({ kb, documents: [document('images/image.png')] });
    expect(screen.getByRole('treeitem', { name: 'images' })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('treeitem', { name: 'image.png' })).toBeInTheDocument();
  });
});
