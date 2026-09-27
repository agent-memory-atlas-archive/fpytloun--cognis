import { describe, expect, it } from 'vitest';
import { tableRows } from './block-helpers';
import { blockTitle } from '$lib/rich-deliverable';

describe('persisted table and heading compatibility', () => {
  it('preserves positional cells under declared column keys', () => {
    expect(tableRows({ type: 'table', columns: ['Target', 'Action'], rows: [['ArgoCD', 'Upgrade'], ['Harbor', 'Backup']] }))
      .toEqual([{ Target: 'ArgoCD', Action: 'Upgrade' }, { Target: 'Harbor', Action: 'Backup' }]);
  });
  it('supports structured columns, typed cells and existing object rows', () => {
    const badge = { type: 'badge', value: 'Ready' };
    expect(tableRows({ type: 'table', columns: [{ key: 'status', label: 'Status' }], rows: [[badge], { status: 'Pending' }] }))
      .toEqual([{ status: badge }, { status: 'Pending' }]);
  });
  it('maps labeled matrix values to columns while retaining metadata and explicit cells', () => {
    const rows = tableRows({
      type: 'comparison_matrix',
      columns: ['Severity', { key: 'component', label: 'Component' }, 'Action'],
      rows: [
        { label: 'Upgrade A', values: ['HIGH', 'ArgoCD', 'Stage upgrade'] },
        { label: 'Upgrade B', values: ['MEDIUM', 'Harbor', 'Back up first'], component: 'Explicit override', recommended: true },
      ],
    });
    expect(rows).toEqual([
      { Severity: 'HIGH', component: 'ArgoCD', Action: 'Stage upgrade', label: 'Upgrade A', values: ['HIGH', 'ArgoCD', 'Stage upgrade'] },
      { Severity: 'MEDIUM', component: 'Explicit override', Action: 'Back up first', label: 'Upgrade B', values: ['MEDIUM', 'Harbor', 'Back up first'], recommended: true },
    ]);
  });
  it('uses heading as a fallback without replacing canonical titles', () => {
    expect(blockTitle({ heading: 'Primary-source evidence' })).toBe('Primary-source evidence');
    expect(blockTitle({ title: 'Canonical', heading: 'Legacy' })).toBe('Canonical');
  });
});
