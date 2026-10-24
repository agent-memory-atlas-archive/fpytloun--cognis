import type { AgentFormState } from '$lib/agents';
import type { Skill } from '$lib/types/api';

export const INSTANCE_MANAGEMENT_TOOLS = [
  { id: 'manage_agents', label: 'Manage agents', description: 'Create, configure, and share your agents.' },
  { id: 'manage_mcp', label: 'Manage MCP', description: 'Configure MCP servers and executor assignments.' },
  { id: 'manage_providers', label: 'Manage providers', description: 'Configure model providers and authentication.' },
  { id: 'manage_routes', label: 'Manage routes', description: 'Configure custom inference routes and system model bindings.' },
  { id: 'manage_settings', label: 'Manage settings', description: 'Configure system settings and workflow step profiles.' },
  { id: 'manage_executors', label: 'Manage executors', description: 'Configure executor connections and availability.' }
];

export const INSTANCE_MANAGEMENT_SKILLS = [
  'cognis-agent-manager', 'cognis-mcp-manager', 'cognis-provider-manager',
  'cognis-route-manager', 'cognis-settings-manager', 'cognis-executor-manager'
];

/** Explicit instance opt-in; this does not bypass owner, role, or approval checks. */
export function configureInstanceManagement(form: AgentFormState, skills: Skill[], enabled: boolean): void {
  const toolIds = new Set(INSTANCE_MANAGEMENT_TOOLS.map((tool) => tool.id));
  form.optInBuiltinTools = form.optInBuiltinTools.filter((id) => !toolIds.has(id));
  if (enabled) form.optInBuiltinTools.push(...toolIds);
  const available = new Set(skills.map((skill) => skill.skill_id));
  const managementSkills = INSTANCE_MANAGEMENT_SKILLS.filter((id) => available.has(id));
  for (const key of ['selectedSkillIds', 'autoLoadSkillIds'] as const) {
    form[key] = form[key].filter((id) => !INSTANCE_MANAGEMENT_SKILLS.includes(id));
    if (enabled) form[key] = [...new Set([...form[key], ...managementSkills])];
  }
}
