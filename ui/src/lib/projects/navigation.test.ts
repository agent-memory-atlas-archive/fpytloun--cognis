import { afterEach, describe, expect, it, vi } from 'vitest';
import { lastProjectUrl, rememberProject } from './navigation';

afterEach(() => { localStorage.clear(); vi.restoreAllMocks(); });
describe('last project navigation', () => {
  it('remembers the latest project and tab per account', () => {
    rememberProject('one@cognis.test', 'proj_first', 'overview');
    rememberProject('one@cognis.test', 'proj_second', 'tasks');
    expect(lastProjectUrl('one@cognis.test', ['proj_first', 'proj_second'])).toBe('/projects/proj_second?tab=tasks');
    expect(lastProjectUrl('two@cognis.test', ['proj_second'])).toBeNull();
    expect(lastProjectUrl(undefined, ['proj_second'])).toBeNull();
  });
  it('clears inaccessible destinations, rather than reviving them later', () => {
    rememberProject('one@cognis.test', 'proj_home', 'settings');
    expect(lastProjectUrl('one@cognis.test', [])).toBeNull();
    expect(lastProjectUrl('one@cognis.test', ['proj_home'])).toBeNull();
  });
  it('constructs only local URLs with a validated tab', () => {
    rememberProject('one@cognis.test', '//external.test', '?redirect=https://external.test');
    expect(lastProjectUrl('one@cognis.test', ['//external.test'])).toBe('/projects/%2F%2Fexternal.test?tab=overview');
  });
  it('tolerates broken data and unavailable storage', () => {
    localStorage.setItem('cognis.projects.lastOpened:one@cognis.test', '{');
    expect(lastProjectUrl('one@cognis.test', [])).toBeNull();
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(() => rememberProject('one@cognis.test', 'proj_home', null)).not.toThrow();
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(lastProjectUrl('one@cognis.test', ['proj_home'])).toBeNull();
  });
});
