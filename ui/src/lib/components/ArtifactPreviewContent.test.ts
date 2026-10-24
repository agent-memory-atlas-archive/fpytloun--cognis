import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import ArtifactPreviewContent from './ArtifactPreviewContent.svelte';
import TextDocument from './TextDocument.svelte';

describe('Shared artifact preview body', () => {
  it.each(['chat', 'library'])('renders canonical CSV payload as inert cells in %s', (surface) => {
    const richPayload = { blocks: [{ type: 'table',
      columns: [{ key: 'value', label: 'Value' }],
      rows: [{ value: { type: 'code', value: '<script>alert(1)</script> =1+1' } }],
    }] };
    const props = { filename: 'data.csv', mime: 'text/csv', richPayload };
    const view = surface === 'chat'
      ? render(ArtifactPreviewContent, { ...props, kind: 'csv', content: 'Value\n=1+1' })
      : render(TextDocument, { ...props, text: 'Value\n=1+1' });
    expect(screen.getByRole('table')).toBeVisible();
    expect(view.container.querySelector('td code')).toHaveTextContent('<script>alert(1)</script> =1+1');
    expect(view.container.querySelector('script')).toBeNull();
  });
  it.each(['audio', 'video'] as const)('renders %s with native controls', (kind) => {
    const { container } = render(ArtifactPreviewContent, {
      kind, filename: `recording.${kind}`, mediaUrl: '/signed-media',
    });
    const media = container.querySelector(kind);
    expect(media).toHaveAttribute('src', '/signed-media');
    expect(media).toHaveAttribute('controls');
  });
  it('refuses HTML URLs without their original account lease', () => {
    render(ArtifactPreviewContent, { kind: 'html', filename: 'page.html', mediaUrl: '/signed-html' });
    expect(screen.queryByTitle('Artifact preview')).toBeNull();
    expect(screen.getByText('The document preview could not be loaded.')).toBeVisible();
  });
  it('shows truncation warnings and leaves malformed JSON readable', () => {
    const { container } = render(ArtifactPreviewContent, {
      kind: 'text', filename: 'data.json', mime: 'application/json', content: '{"partial":', truncated: true,
    });
    expect(container.querySelector('code')).toHaveTextContent('{"partial":');
    expect(screen.getByText(/Download the complete file/)).toBeVisible();
    expect(container.querySelector('.json-key')).toBeNull();
  });
});
