export interface DashboardLaunchInput {
  kind: 'conversation' | 'task' | 'schedule' | 'artifact' | 'deliverable';
  id: string;
  title: string;
  project_id: string | null;
  agent_id?: string | null;
  status?: string | null;
  href: string;
}

export interface DashboardLauncher {
  projectId: string | null;
  open(input: DashboardLaunchInput): Promise<void>;
}

let current: DashboardLauncher | null = null;

/** Only the mounted ControlCenter registers; callers own scope and redirect policy. */
export function registerDashboardLauncher(launcher: DashboardLauncher): () => void {
  const registration: DashboardLauncher = {
    projectId: launcher.projectId,
    async open(input) {
      if (current !== registration) throw new Error('Dashboard launcher is no longer active.');
      await launcher.open(input);
    },
  };
  current = registration;
  return () => {
    if (current === registration) current = null;
  };
}

export function getDashboardLauncher(): DashboardLauncher | null {
  return current;
}
