import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import ResultIcon from './ResultIcon.svelte';
import { PaletteThumbnails } from '$lib/palette/thumbnails';
import type { PaletteItem } from '$lib/palette/model';

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', class {
    observe() {}
    disconnect() {}
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function show(settings: Partial<PaletteItem> = {}) {
  const sign = vi.fn(async () => ({ url: '/signed-thumbnail' }));
  const item: PaletteItem = {
    kind: 'project', id: 'palette-project', title: 'Palette project',
    project_id: 'palette-project', agent_id: null, status: 'active', format: null,
    updated_at: '2026-01-01T00:00:00Z', href: '/projects/palette-project?tab=overview',
    ...settings,
  };
  return { ...render(ResultIcon, { item, thumbnails: new PaletteThumbnails(sign) }), sign };
}

describe('project result identity', () => {
  it('prefers the configured avatar over the icon without signing or fetching a project', () => {
    const view = show({
      project_avatar_url: '/api/v1/images/project-avatar',
      project_icon: 'cognis', project_color: '#fbbf24',
    });
    expect(view.getByRole('img', { name: 'Palette project' })).toHaveAttribute(
      'src', '/api/v1/images/project-avatar',
    );
    expect(view.queryByTestId('project-library-icon')).not.toBeInTheDocument();
    expect(view.sign).not.toHaveBeenCalled();
  });

  it('uses the canonical selected project icon and color when no avatar is configured', () => {
    const view = show({ project_icon: 'cognis', project_color: '#fbbf24' });
    const icon = view.getByTestId('project-library-icon');
    expect(icon).toHaveAccessibleName('Palette project');
    expect(icon).toHaveStyle({ backgroundColor: 'rgb(251, 191, 36)' });
    expect(icon.innerHTML).toContain('/brand/cognis-mark.svg');
    expect(view.sign).not.toHaveBeenCalled();
  });

  it('falls back to the configured project icon when its avatar fails', async () => {
    const view = show({
      project_avatar_url: '/api/v1/images/project-avatar',
      project_icon: 'cognis', project_color: '#fbbf24',
    });
    await fireEvent.error(view.getByRole('img', { name: 'Palette project' }));
    expect(view.getByTestId('project-library-icon').innerHTML).toContain('/brand/cognis-mark.svg');
    expect(view.getByTestId('project-library-icon')).toHaveStyle({
      backgroundColor: 'rgb(251, 191, 36)',
    });
  });

  it('retains safe canonical defaults for missing or malformed settings', () => {
    const view = show({ project_icon: 'unrecognized', project_color: 'invalid-color' });
    expect(view.getByTestId('project-library-icon')).toHaveAccessibleName('Palette project');
    expect(view.getByTestId('project-library-icon')).toHaveStyle({
      backgroundColor: 'rgb(56, 189, 248)',
    });
    expect(view.sign).not.toHaveBeenCalled();
  });
});
