import { fireEvent, render, screen, cleanup } from '@testing-library/svelte';
import { afterEach, expect, it, vi } from 'vitest';
import { resultTypes } from '$lib/palette/model';
import TypeFilter from './TypeFilter.svelte';

afterEach(cleanup);

it('is a multi-select menu rather than a form field', async () => {
  const onchange = vi.fn();
  const { rerender } = render(TypeFilter, { selected: [...resultTypes], onchange });
  await fireEvent.click(screen.getByRole('button', { name: 'Filter result types' }));
  const task = screen.getByRole('menuitemcheckbox', { name: 'Tasks' });
  expect(task.getAttribute('aria-checked')).toBe('true');
  await fireEvent.click(task);
  expect(onchange).toHaveBeenLastCalledWith(resultTypes.filter(type => type !== 'task'));
  await rerender({ selected: [], onchange });
  expect(screen.getByRole('button', { name: 'Filter result types' }).textContent).toContain('0 types');
  await fireEvent.click(screen.getByRole('menuitem', { name: 'All types' }));
  expect(onchange).toHaveBeenLastCalledWith([...resultTypes]);
});

it('keeps arrow and Escape navigation inside the menu and restores trigger focus', async () => {
  render(TypeFilter, { selected: [...resultTypes], onchange: vi.fn() });
  const trigger = screen.getByRole('button', { name: 'Filter result types' });
  trigger.focus();
  await fireEvent.keyDown(trigger, { key: 'ArrowDown' });
  expect(document.activeElement).toBe(screen.getByRole('menuitem', { name: 'All types' }));
  await fireEvent.keyDown(document.activeElement!, { key: 'ArrowUp' });
  expect(document.activeElement).toBe(screen.getByRole('menuitemcheckbox', { name: 'Settings' }));
  await fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
  expect(screen.queryByRole('menu')).toBeNull();
  expect(document.activeElement).toBe(trigger);
});
