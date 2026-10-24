import { afterEach, expect, it } from 'vitest';
import { sidebarTooltip } from './sidebarTooltip';

afterEach(() => document.body.replaceChildren());

it('portals a semantic tooltip and preserves its focus, update and cleanup lifecycle', () => {
  const trigger = document.createElement('button');
  document.body.appendChild(trigger);
  const action = sidebarTooltip(trigger, 'Dashboard');
  trigger.dispatchEvent(new FocusEvent('focusin'));
  const tooltip = document.querySelector('[role="tooltip"]') as HTMLElement;
  expect(tooltip.parentElement).toBe(document.body);
  expect(tooltip).toHaveTextContent('Dashboard');
  expect(tooltip).toHaveClass('bg-elevated', 'text-foreground', 'border-control-border', 'shadow-overlay');
  expect(tooltip.className).not.toMatch(/(?:bg|text|border)-slate-/);
  action.update('Projects');
  expect(tooltip).toHaveTextContent('Projects');
  trigger.dispatchEvent(new FocusEvent('focusout'));
  expect(tooltip.style.opacity).toBe('0');
  action.destroy();
  expect(document.querySelector('[role="tooltip"]')).toBeNull();
  trigger.dispatchEvent(new MouseEvent('mouseenter'));
  expect(document.querySelector('[role="tooltip"]')).toBeNull();
});
