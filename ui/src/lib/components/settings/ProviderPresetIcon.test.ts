import { cleanup, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import ProviderPresetIcon from './ProviderPresetIcon.svelte';

afterEach(cleanup);

describe('provider brand assets', () => {
  for (const [preset, file] of Object.entries({
    openrouter: 'openrouter', openai: 'openai', anthropic: 'anthropic', chatgpt: 'codex'
  })) {
    it(`uses the bundled ${file} brand asset for ${preset}`, () => {
      const { container } = render(ProviderPresetIcon, { preset });
      expect(container.querySelector('img')?.getAttribute('src')).toBe(`/providers/${file}.svg`);
      expect(container.querySelector('svg')).toBeNull();
      const svg = readFileSync(`static/providers/${file}.svg`, 'utf8');
      expect(svg).toContain('<svg');
      expect(svg).not.toMatch(/<script|<foreignObject|(?:href|src)=["']https?:/i);
    });
  }
  it('reserves the generic settings glyph for custom providers', () => {
    const { container } = render(ProviderPresetIcon, { preset: 'custom' });
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('svg')).not.toBeNull();
  });
});
