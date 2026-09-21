import { fireEvent, render, screen } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import TooltipFixture from './Tooltip.test-fixture.svelte';

describe('Tooltip', () => {
  beforeEach(() => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
  });

  it('does not open from touch or focus when touch presentation is disabled', async () => {
    render(TooltipFixture, { showOnTouch: false });
    const trigger = screen.getByRole('button', { name: 'Toolbar action' });

    await fireEvent.pointerDown(trigger, { pointerType: 'touch' });
    await fireEvent.focusIn(trigger);

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });
});
