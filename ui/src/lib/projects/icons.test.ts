import { describe, expect, it } from 'vitest';
import { projectIcon, projectIconForeground, safeProjectColor } from './icons';

describe('project icon identity', () => {
  it('resolves only bundled icons, never dynamic markup', () => {
    expect(projectIcon('suitcase')).toBeDefined();
    expect(projectIcon('<svg onload=alert(1)>')).toBeUndefined();
    expect(projectIcon(null)).toBeUndefined();
  });
  it('uses contrasting foregrounds for light and dark project colors', () => {
    expect(projectIconForeground('#ffffff')).toBe('#0f172a');
    expect(projectIconForeground('#000000')).toBe('#ffffff');
    expect(projectIconForeground('#fbbf24')).toBe('#0f172a');
    expect(projectIconForeground('#1e3a8a')).toBe('#ffffff');
    expect(safeProjectColor('url(https://external.test)')).toBe('#38bdf8');
  });
});
