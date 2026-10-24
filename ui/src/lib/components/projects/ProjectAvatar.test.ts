import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import ProjectAvatar from './ProjectAvatar.svelte';

afterEach(cleanup);
describe('project avatar precedence', () => {
  it('keeps the uploaded image even when an icon is configured', () => {
    render(ProjectAvatar, { name: 'Travel', avatarUrl: '/photo.png', icon: 'suitcase', color: '#fbbf24' });
    expect(screen.queryByTestId('project-library-icon')).not.toBeInTheDocument();
    expect(screen.getByRole('img')).toHaveAttribute('src', '/photo.png');
    expect(screen.getByRole('img')).toHaveClass('rounded-[22%]');
    expect(screen.getByRole('img')).not.toHaveClass('rounded-full');
  });
  it('uses the selected icon after the avatar is removed', () => {
    render(ProjectAvatar, { name: 'Travel', avatarUrl: null, icon: 'suitcase', color: '#fbbf24' });
    expect(screen.getByTestId('project-library-icon')).toHaveStyle({ backgroundColor: '#fbbf24', color: '#0f172a' });
  });
  it('has a default fallback without either value', () => {
    render(ProjectAvatar, { name: 'Project' });
    expect(screen.getByTestId('project-library-icon')).toBeInTheDocument();
  });
  it('uses canonical Cognis artwork', () => {
    const { container } = render(ProjectAvatar, { name: 'Cognis', icon: 'cognis', color: '#000000' });
    expect(screen.getByTestId('project-library-icon')).toHaveStyle({ color: '#ffffff' });
    expect(container.innerHTML).toContain('/brand/cognis-mark.svg');
  });
});
