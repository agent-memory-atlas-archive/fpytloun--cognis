import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const page = readFileSync(
  resolve('src/routes/(app)/chat/[conversationId]/+page.svelte'),
  'utf8',
);

describe('chat sidebar reconciliation ownership', () => {
  it('routes every owner-wide sidebar invalidation through the serial coalescer', () => {
    expect(page).toContain("if (event.type === 'work_invalidated')");
    expect(page).toContain("scheduleSidebarReconciliation('work-invalidation')");
    expect(page).toContain("scheduleSidebarReconciliation('owner-sidebar-invalidation')");
    expect(page).toContain("scheduleSidebarReconciliation('cluster-invalidation')");
    expect(page).not.toContain(
      "void resyncSidebarData('owner-sidebar-invalidation', { force: true })",
    );
    expect(page).not.toContain(
      "void resyncSidebarData('cluster-invalidation', { force: true })",
    );
  });

  it('records Work revision targets and disposes sidebar reconciliation', () => {
    expect(page).toContain('sidebarRevisionAdmission.observeInvalidation(event.revision)');
    expect(page).toContain('onDestroy(() => sidebarReconciliation.dispose())');
  });

  it('loads current filters when each admitted reconciliation attempt starts', () => {
    expect(page).toContain('new SidebarRefreshController(');
    expect(page).toContain("await performSidebarResync('sidebar-invalidation', {");
    expect(page).toContain('const filters = {\n      contextTypes: selectedChannels');
    expect(page).toContain('const filterKey = sidebarProjectionCacheKey()');
    expect(page).toContain('if (filterKey !== sidebarProjectionCacheKey())');
    expect(page).toContain(
      "scheduleSidebarReconciliation('changed-sidebar-resync-filter')",
    );
    expect(page).toContain("scheduleSidebarReconciliation('changed-sidebar-filter')");
    expect(page).toContain(
      "scheduleSidebarReconciliation('changed-restored-sidebar-filter')",
    );
    expect(page).toContain('const requestEpoch = ++sidebarProjectionRefreshEpoch');
  });

  it('retains recovery when an ordinary request supersedes or rejects a response', () => {
    expect(page).toContain("ensureSidebarRecoveryIfBehind('superseded-sidebar-load'");
    expect(page).toContain("ensureSidebarRecoveryIfBehind('rejected-sidebar-load'");
    expect(page).toContain("ensureSidebarRecoveryIfBehind('failed-sidebar-load'");
    expect(page).toContain('recoveryAttempt: true');
    expect(page).toContain(
      'sidebarReconciliation.request(filterKey, { full: true })',
    );
    expect(page).toContain(
      'if (!options.recoveryAttempt && sidebarRevisionAdmission.needsReconciliation)',
    );
  });

  it('keeps full loads, recovery, and Waiting under scoped coordination', () => {
    expect(page).toContain('sidebarReconciliation.request(scope, { full: true');
    expect(page).toContain('waitingReconciliation.request(scope');
    expect(page).toContain('onDestroy(() => waitingReconciliation.dispose())');
    expect(page).toContain("scheduleSidebarReconciliation('missing-sidebar-upsert')");
    expect(page).not.toContain('waitingLoadError = projection.waiting_error');
    expect(page).not.toContain('loadAgentDirectChats');
    expect(page).not.toContain('api.conversations.agentDirect(');
    expect(page).toContain('updateWaitingCaches(conversationId, () => null)');
    expect(page).toContain('updateWaitingCaches(conversationId, item => mergeAuthoritativeSidebarConversation');
  });
});
