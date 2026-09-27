import { fireEvent, render as renderComponent, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import RichDeliverable from './RichDeliverable.svelte';
import { richDeliverableEvidenceFixture } from './rich-deliverable-evidence.fixture';

function render(_: typeof RichDeliverable, props: { payload: unknown; surface?: 'embedded' | 'standalone' } & Record<string, unknown>) {
  return renderComponent(RichDeliverable, { surface: 'standalone', ...props });
}

describe('RichDeliverable evidence interactions', () => {
  it('renders citation chips with safe source popovers and source rail metadata', async () => {
    render(RichDeliverable, {
      payload: richDeliverableEvidenceFixture,
      content: 'Fallback',
      title: 'Evidence report',
    });

    const citation = screen.getByRole('button', { name: /Citation 1: Renderer-owned interactivity notes/i });
    await fireEvent.click(citation);

    expect(screen.getByRole('dialog', { name: /Source Renderer-owned interactivity notes/i })).toBeTruthy();
    expect(screen.getAllByText(/Interactions are declarative/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole('link', { name: 'Open source' })).toHaveAttribute('href', 'https://cognis.local/docs/rich-renderer');

    await fireEvent.click(screen.getByRole('button', { name: /Citation 2: Unsafe source should not link/i }));
    const unsafePopover = screen.getByRole('dialog', { name: /Source Unsafe source should not link/i });
    expect(within(unsafePopover).queryByRole('link', { name: 'Open source' })).toBeNull();
  });

  it('renders evidence claims with confidence, snippets, caveats, and contradictions', async () => {
    render(RichDeliverable, {
      payload: richDeliverableEvidenceFixture,
      content: 'Fallback',
      title: 'Evidence report',
    });

    expect(screen.getByText('Evidence quality')).toBeTruthy();
    expect(screen.getByLabelText('Confidence High')).toBeTruthy();
    expect(screen.getByLabelText('Confidence Medium')).toBeTruthy();

    await fireEvent.click(screen.getAllByText('Evidence snippets')[0]);
    expect(screen.getByText('Payloads remain renderer-neutral while the UI owns interaction state.')).toBeTruthy();
    expect(screen.getByText('Citation snippets are summaries, not independently fetched browser pages.')).toBeTruthy();
    expect(screen.getByText('A static PDF export would need non-interactive fallbacks.')).toBeTruthy();
  });

  it('renders a claim field as the body when a claim card has a separate title', () => {
    render(RichDeliverable, {
      content: 'Fallback',
      payload: {
        blocks: [{
          type: 'evidence_report',
          claims: [{
            label: 'Recommendation',
            title: 'Pick the verified option',
            claim: 'It has the strongest evidence for the stated requirements.',
            confidence: 'high',
          }],
        }],
      },
    });

    expect(screen.getByText('Pick the verified option')).toBeTruthy();
    expect(screen.getByText('It has the strongest evidence for the stated requirements.')).toBeTruthy();
  });

  it('sorts decision rows and expands row evidence', async () => {
    const { container } = render(RichDeliverable, {
      payload: richDeliverableEvidenceFixture,
      content: 'Fallback',
      title: 'Evidence report',
    });

    const matrix = container.querySelector('[data-rich-block-type="decision_matrix"]');
    if (!matrix) throw new Error('matrix not found');

    await fireEvent.click(within(matrix as HTMLElement).getByRole('button', { name: 'Sort by Score' }));
    const cells = within(matrix as HTMLElement).getAllByRole('cell', { name: /Micro-app payloads|Static Markdown|Renderer-owned blocks/ });
    expect(cells[0]).toHaveTextContent('Micro-app payloads');

    await fireEvent.click(within(matrix as HTMLElement).getAllByRole('button', { name: 'Show evidence' })[0]);
    expect(screen.getByText('Would let payloads define behavior instead of data.')).toBeTruthy();
    expect(screen.getByText('Recommended')).toBeTruthy();
  });

  it('omits empty evidence columns and renders row source citations when available', async () => {
    const { container, rerender } = render(RichDeliverable, {
      content: 'Fallback',
      payload: {
        blocks: [{
          type: 'comparison_matrix',
          columns: ['name', 'price'],
          rows: [{ name: 'Product A', price: '100' }, { name: 'Product B', price: '120' }],
        }],
      },
    });

    const emptyEvidenceMatrix = container.querySelector('[data-rich-block-type="comparison_matrix"]');
    expect(within(emptyEvidenceMatrix as HTMLElement).queryByText('Evidence')).toBeNull();

    await rerender({
      content: 'Fallback',
      payload: {
        sources: [{ id: 'manufacturer', title: 'Manufacturer specification', url: 'https://example.test/spec' }],
        blocks: [{
          type: 'comparison_matrix',
          sources: ['manufacturer'],
          columns: ['name', 'price'],
          rows: [{ name: 'Product A', price: '100', source_ids: ['manufacturer'] }],
        }],
      },
    });

    const sourcedMatrix = container.querySelector('[data-rich-block-type="comparison_matrix"]');
    expect(within(sourcedMatrix as HTMLElement).getByText('Evidence')).toBeTruthy();
    await fireEvent.click(within(sourcedMatrix as HTMLElement).getByRole('button', { name: 'Show sources' }));
    expect(within(sourcedMatrix as HTMLElement).getByRole('link', { name: /\[1\] Manufacturer specification/ })).toHaveAttribute('href', 'https://example.test/spec');
  });

  it('renders and sorts labeled positional comparison rows without dropping cells', async () => {
    const { container } = render(RichDeliverable, {
      content: 'Fallback',
      payload: {
        blocks: [{
          type: 'comparison_matrix',
          columns: ['Severity', 'Component', 'Recommended action'],
          rows: [
            { label: 'Upgrade A', values: ['HIGH', 'ArgoCD', 'Stage upgrade'] },
            { label: 'Upgrade B', values: ['MEDIUM', 'Harbor', 'Back up first'] },
          ],
        }],
      },
    });
    const matrix = container.querySelector('[data-rich-block-type="comparison_matrix"]') as HTMLElement;
    const cells = within(matrix).getAllByRole('cell');
    expect(cells.map((cell) => cell.textContent)).toEqual([
      'HIGH', 'ArgoCD', 'Stage upgrade', 'MEDIUM', 'Harbor', 'Back up first',
    ]);
    await fireEvent.click(within(matrix).getByRole('button', { name: 'Sort by Component' }));
    expect(within(matrix).getAllByRole('row')[1]).toHaveTextContent('ArgoCD');
  });

  it('keeps section prose, card evidence and verdicts, and callout text from a workload report', () => {
    const { container } = render(RichDeliverable, {
      title: 'Workload review',
      content: 'Fallback',
      payload: { blocks: [
        { type: 'section', heading: 'Deployed this run', body: 'Both upgrades are live and verified.' },
        { type: 'claim_cards', title: 'Skipped before mutation', cards: [
          { claim: 'Infra doc correction not applied', evidence: 'Historical records must remain unchanged.', verdict: 'Correctly deferred' },
          { claim: 'Kernel dist-upgrade not performed', evidence: 'No established host-access path.', verdict: 'Blocked on tooling' },
        ] },
        { type: 'callout', variant: 'warning', text: 'Residual follow-ups require an approved window.' },
      ] },
    });
    const section = container.querySelector('[data-rich-block-type="section"]') as HTMLElement;
    expect(section).toHaveTextContent('Both upgrades are live and verified.');
    const cards = container.querySelector('[data-rich-block-type="claim_cards"]') as HTMLElement;
    expect(within(cards).getAllByRole('article')).toHaveLength(2);
    expect(cards).toHaveTextContent('Historical records must remain unchanged.');
    expect(cards).toHaveTextContent('Correctly deferred');
    expect(cards).toHaveTextContent('No established host-access path.');
    expect(within(cards).queryByLabelText('Confidence Unknown')).toBeNull();
    expect(container.querySelector('[data-rich-block-type="callout"]')).toHaveTextContent('Residual follow-ups require an approved window.');
  });

  it('renders source citations for a direct research answer', () => {
    render(RichDeliverable, {
      content: 'Fallback',
      payload: {
        sources: [{ id: 'manufacturer', title: 'Manufacturer specification', url: 'https://example.test/spec' }],
        blocks: [{
          type: 'research_answer',
          answer: 'Product A is the strongest fit.',
          source_ids: ['manufacturer'],
        }],
      },
    });

    expect(screen.getByRole('button', { name: 'Citation 1: Manufacturer specification' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Manufacturer specification' })).toHaveAttribute('href', 'https://example.test/spec');
  });
});
