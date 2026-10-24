import { beforeEach, describe, expect, it } from 'vitest';

import { clearPerfLog, readPerfLog, recordPerf } from './perf-log';

describe('perf log', () => {
  beforeEach(() => window.localStorage.clear());

  it('records bounded entries with rounded durations', () => {
    for (let index = 0; index < 70; index += 1) recordPerf({ kind: 'switch', path: 'sync', ms: index + 0.4 });
    const entries = readPerfLog();
    expect(entries).toHaveLength(60);
    expect(entries.at(-1)).toMatchObject({ kind: 'switch', path: 'sync', ms: 69 });
    clearPerfLog();
    expect(readPerfLog()).toEqual([]);
  });

  it('tolerates corrupt storage', () => {
    window.localStorage.setItem('cognis-perf-log', '{not json');
    expect(readPerfLog()).toEqual([]);
    recordPerf({ kind: 'sidebar', path: 'device', ms: 12 });
    expect(readPerfLog()).toHaveLength(1);
  });
});
