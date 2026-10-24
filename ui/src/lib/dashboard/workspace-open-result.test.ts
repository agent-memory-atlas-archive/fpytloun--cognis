import { describe, expect, it } from 'vitest';
import { workspaceCapacityReason, workspaceOpenFailure, workspaceOpenFailureMessage } from './workspace-open-result';

describe('workspace open failure contract', () => {
  it.each(['capacity', 'permission-denied', 'scope-changed', 'uncertain', 'owner-unavailable', 'unknown'])(
    'never classifies %s as a known capacity reason', (reason) => {
      expect(workspaceOpenFailure(reason)).toEqual({ status: 'failed', reason });
    },
  );
  it('distinguishes actionable visible, retained, and agent limits', () => {
    const visible = workspaceOpenFailureMessage({ status: 'capped', limit: 5 });
    const retained = workspaceOpenFailureMessage(workspaceOpenFailure(workspaceCapacityReason.retained));
    const agents = workspaceOpenFailureMessage(workspaceOpenFailure(workspaceCapacityReason.agents));
    expect(visible).toContain('Visible window limit reached (5)');
    expect(visible).toContain('Minimize or close');
    expect(retained).toContain('including minimized');
    expect(retained).not.toContain('Minimize or close');
    expect(agents).toContain('Pinned agent limit reached (10)');
    expect(agents).toContain('Unpin an agent explicitly');
  });
  it('reports uncertainty without advising automatic mutation retries', () => {
    expect(workspaceOpenFailureMessage({ status: 'failed', reason: 'uncertain' })).toContain('Wait for workspace synchronization');
  });
});
