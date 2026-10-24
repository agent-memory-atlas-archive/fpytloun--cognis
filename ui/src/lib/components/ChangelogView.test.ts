import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import ChangelogView from './ChangelogView.svelte';
import { releasesBetween, type Release } from '$lib/changelog';

const releases: Release[] = [
  { version: '0.18.0', date: 'Unreleased', markdown: '### Added\n\n- New release browser.' },
  { version: '0.17.1', date: '2026-09-28', markdown: '### Fixed\n\n- Stable replay.' },
  { version: '0.10.0', date: '2026-08-01', markdown: '### Added\n\n- Earlier features.' },
  { version: '0.9.0', date: '2026-07-01', markdown: '### Fixed\n\n- Older fixes.' }
];

describe('release history', () => {
  it('compares numeric versions with an exclusive lower bound', () => {
    expect(releasesBetween(releases, '0.9.0', '0.17.1').map((r) => r.version))
      .toEqual(['0.17.1', '0.10.0']);
    expect(releasesBetween(releases, '0.18.0', '0.17.1')).toEqual([]);
    expect(releasesBetween(releases, '0.1.0', '0.18.0')).toEqual([]);
    expect(releasesBetween(releases, '', '0.1.0')).toEqual([]);
  });

  it('renders history, labels previews, and compares selected versions', async () => {
    render(ChangelogView, { releases });
    expect(await screen.findByText('Unreleased · preview')).toBeInTheDocument();
    expect(screen.getByText('Stable replay.')).toBeInTheDocument();
    await fireEvent.change(screen.getByLabelText('Changes after'), { target: { value: '0.17.1' } });
    await waitFor(() => expect(screen.queryByText('Stable replay.')).not.toBeInTheDocument());
    expect(screen.getByText('New release browser.')).toBeInTheDocument();
    expect(screen.getByText('Link to this comparison')).toHaveAttribute(
      'href', '/docs/changelog?since=0.17.1&through=0.18.0'
    );
  });

  it('restores a linked comparison and explains an empty range', async () => {
    const { rerender } = render(ChangelogView, {
      releases, initialSince: '0.9.0', initialThrough: '0.17.1'
    });
    expect(await screen.findByText('Stable replay.')).toBeInTheDocument();
    expect(screen.queryByText('New release browser.')).not.toBeInTheDocument();
    await rerender({ releases, initialSince: '0.18.0', initialThrough: '0.17.1' });
    expect(await screen.findByRole('status')).toHaveTextContent('No releases in this range');
  });

  it('handles an installation without release notes', () => {
    render(ChangelogView, { releases: [] });
    expect(screen.getByText('No release notes are bundled with this installation.')).toBeInTheDocument();
  });

  it('uses the normal sanitized Markdown boundary', async () => {
    const { container } = render(ChangelogView, {
      releases: [{ ...releases[0], markdown: 'Safe release note.\n\n<script>alert(1)</script>\n\n[Unsafe](javascript:alert)' }]
    });
    await screen.findByText('Safe release note.');
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
  });
});
