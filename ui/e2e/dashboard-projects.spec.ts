import { expect, test } from '@playwright/test';
import { installTaskCockpitFixture } from './task-cockpit-fixture';

test.use({ serviceWorkers: 'block' });
for (const width of [390, 1280]) {
  test(`dashboard project strip and shared row filters at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await installTaskCockpitFixture(page);
    await page.route('**/api/v1/inbox**', (route) => route.fulfill({ json: { items: [], unread_count: 0, has_more: false, cursor: null } }));
    await page.route('**/api/v1/provider-monitor', (route) => route.fulfill({ json: [] }));
    await page.route('**/api/v1/schedules', (route) => route.fulfill({ json: [] }));
    await page.route('**/api/auth/me', (route) => route.fulfill({ json: { email: 'owner@cognis.test', role: 'admin' } }));
    await page.route('**/api/health**', (route) => route.fulfill({ json: { status: 'ok', providers: {} } }));
    await page.route('**/api/v1/dashboard/issues', (route) => route.fulfill({ json: { issues: [], summary: { total: 0 } } }));
    const projects = Array.from({ length: 16 }, (_, index) => ({
      project_id: `proj_${index}`, name: index ? `Project ${index}` : 'Cognis',
      metadata: { icon: index ? 'suitcase' : 'cognis' }, color: '#34d399', avatar_url: null,
    }));
    await page.route('**/api/v1/projects?**', (route) => route.fulfill({ json: projects }));
    let taskFilter: string | null = null;
    let chatFilter: string | null = null;
    await page.route('**/api/v1/tasks/board**', (route) => {
      taskFilter = new URL(route.request().url()).searchParams.get('project_id');
      return route.fulfill({ json: { columns: { running: { total_count: 1, has_more: false, items: [{
        task_id: 'task_project', title: 'Task title stays unchanged', agent_id: 'agent-stage39', status: 'running',
        project_id: 'proj_0', priority: 1, progress_summary: { todo_total: 3, todo_completed: 1, todo_in_progress: 1 },
      }] } } } });
    });
    await page.route(/\/api\/v1\/conversations(?:\?|$)/, (route) => {
      chatFilter = new URL(route.request().url()).searchParams.get('project_id');
      return route.fulfill({ json: { items: [{
        conversation_id: 'conv_project', title: 'Conversation title stays unchanged', agent_id: 'agent-stage39',
        project_id: 'proj_0', context: { type: 'web' }, status: 'active',
      }], has_more: false, cursor: null } });
    });
    await page.goto('/');
    const projectsTab = page.getByRole('tab', { name: /Projects/ });
    await expect(projectsTab).toHaveAttribute('aria-selected', 'true', { timeout: 30000 });
    const strip = page.getByTestId('dashboard-project-strip');
    await expect(strip.getByRole('link').first()).toHaveAttribute('href', '/projects/proj_0');
    expect(await strip.evaluate((node) => node.scrollWidth > node.clientWidth)).toBe(true);
    const task = page.getByTestId('dashboard-task-row-task_project');
    const chat = page.getByTestId('dashboard-conversation-row-conv_project');
    const taskBadge = task.getByTestId('conversation-project-badge');
    const chatBadge = chat.getByTestId('conversation-project-badge');
    await expect(taskBadge).toBeVisible();
    await expect(chatBadge).toBeVisible();
    for (const [row, id] of [[task, 'dashboard-task-row-link-task_project'], [chat, 'dashboard-conversation-row-link-conv_project']] as const) {
      const title = row.getByTestId('dashboard-row-title');
      const action = title.getByTestId(id);
      await expect(action).toBeVisible();
      await expect(row.getByTestId('dashboard-row-indicators').getByTestId(id)).toHaveCount(0);
      const textBox = await title.locator('p').boundingBox();
      const actionBox = await action.boundingBox();
      const indicatorsBox = await row.getByTestId('dashboard-row-indicators').boundingBox();
      expect(actionBox!.x).toBeGreaterThanOrEqual(textBox!.x + textBox!.width);
      expect(Math.abs(actionBox!.y - textBox!.y)).toBeLessThan(1);
      expect(actionBox!.x + actionBox!.width).toBeLessThanOrEqual(indicatorsBox!.x);
    }
    await taskBadge.click();
    await expect.poll(() => [taskFilter, chatFilter]).toEqual(['proj_0', 'proj_0']);
    await expect(page.getByLabel('Filter dashboard by project')).toHaveValue('proj_0');
    await expect(page.getByTestId('dashboard-entity-modal')).toHaveCount(0);
    await chatBadge.focus();
    await page.keyboard.press('Enter');
    await expect.poll(() => [taskFilter, chatFilter]).toEqual([null, null]);
    await expect(page.getByLabel('Filter dashboard by project')).toHaveValue('');
    expect(new URL(page.url()).pathname).toBe('/');
    await page.screenshot({ path: test.info().outputPath(`dashboard-projects-${width}.png`) });
    await page.reload();
    await expect(projectsTab).toHaveAttribute('aria-selected', 'true');
  });
}
