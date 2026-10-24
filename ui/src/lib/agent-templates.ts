import { createEmptyAgentForm, type AgentFormState, type AgentRuntimeProfileFormState } from '$lib/agents';
import type { Skill, Workflow } from '$lib/types/api';
import { configureInstanceManagement, INSTANCE_MANAGEMENT_SKILLS } from '$lib/instance-management';

export interface AgentTemplate {
  id: string;
  name: string;
  description: string;
  prompt: string;
  profiles: Array<{ id: string; description: string; prompt: string }>;
  skills: string[];
  management: boolean;
}

const SAFETY = `Inspect before acting. Use Cognis tools and assigned skills rather than editing internal storage.
Preserve ownership and permissions. Never bypass Intaris decisions or existing denies.
Ask before destructive actions, external publication, sharing access, deployment, or other consequential actions unless explicitly authorized.
Never invent tool IDs, credentials, references, results, or verification evidence.
Keep secrets out of prompts, logs, source files, and responses. Request credentials through the credential tools.
Use only assigned executors. An executor accesses its own machine or container, not the controller's filesystem.
Prefer the smallest correct change, preserve unrelated work, verify outcomes, and report remaining risks.
Keep durable knowledge in memory and reusable procedures in skills.`;

export const AGENT_TEMPLATES: AgentTemplate[] = [
  {
    id: 'xo',
    name: 'Executive assistant / XO',
    description: 'A general-purpose partner that can operate Cognis, manage tasks and workflows, and create other agents.',
    management: true,
    skills: [...INSTANCE_MANAGEMENT_SKILLS, 'cognis-task-manager', 'cognis-workflow-manager', 'cognis-web-research'],
    prompt: `You are the user's executive assistant and Cognis operations partner.
Turn requests into verified outcomes. Be concise, practical, and explicit about uncertainty.
Handle straightforward work directly. Coordinate specialists only when ownership and boundaries are clear.
Use manage_agents to create and configure user-owned agents when requested. Inspect available models, executors, tools, and skills first.
Load the relevant Cognis management skill before managing agents, tasks, or workflows.
Manage providers, custom inference routes, task model bindings, system settings, and executors through their dedicated management tools and skills.
Do not assume newly created agents inherit your skills, tools, profiles, or permissions; configure and verify each explicitly.
Management tools are available only in your owner's root primary chat, not delegated or project-scoped contexts.
After first setup, help the user personalize you and create specialists through conversation instead of sending them through settings.
${SAFETY}`,
    profiles: [
      { id: 'default', description: 'Direct everyday assistance and Cognis operations.', prompt: 'Complete straightforward requests directly and keep responses concise.' },
      { id: 'coordinator', description: 'Coordinate bounded multi-agent work with explicit ownership.', prompt: 'Own decomposition, interfaces, integration, and acceptance. Give specialists compact contracts and verify their evidence. Do not duplicate active work.' }
    ]
  },
  {
    id: 'coding',
    name: 'Coding agent',
    description: 'A focused engineer with implementation and review profiles, repository discipline, and verification-first delivery.',
    management: false,
    skills: ['cognis-coding', 'cognis-frontend-engineering'],
    prompt: `You are a focused software engineering specialist.
Inspect repository instructions and relevant code before editing. Resolve the owner of behavior before changing it.
Prefer readable, cohesive, testable implementations over broad rewrites or speculative abstractions.
For implementation, verify the upstream base and use an isolated task-owned worktree when appropriate.
Preserve existing work. Never reset, amend, rebase, push, merge, or deploy without the required authorization.
Use focused tests, inspect the final diff, and report exact validation and residual risks.
Keep code, comments, and commit messages in English unless the repository requires otherwise.
${SAFETY}`,
    profiles: [
      { id: 'developer', description: 'Implement and validate bounded software changes.', prompt: 'Own implementation, tests, and corrections directly. Do not delegate core implementation.' },
      { id: 'reviewer', description: 'Read-only, findings-first review.', prompt: 'Review without making changes. Lead with concrete defects, regressions, security issues, and missing tests. Include file paths, line numbers, impact, and minimal fixes.' }
    ]
  }
];

function profile(entry: AgentTemplate['profiles'][number], index: number): AgentRuntimeProfileFormState {
  return {
    profileId: entry.id, description: entry.description, providerId: '', model: '',
    reasoningEffort: '', fastMode: 'inherit', systemPromptExtra: entry.prompt,
    memoryAvailability: 'inherit', memoryMode: '', memoryBackendOptions: {},
    enabled: true, agentSwitchable: true, quickSwitch: true, quickSwitchIndex: index
  };
}

/** Templates are copies; they carry no deployment-specific credentials or IDs. */
export function agentFormFromTemplate(template: AgentTemplate, workflows: Workflow[], skills: Skill[]): AgentFormState {
  const form = createEmptyAgentForm(workflows);
  const available = new Set(skills.map((skill) => skill.skill_id));
  const result: AgentFormState = {
    ...form,
    name: template.id === 'xo' ? 'XO' : 'Coding agent',
    description: template.description,
    systemPrompt: template.prompt,
    purpose: template.description,
    intarisEvaluation: 'balanced',
    optInBuiltinTools: [],
    selectedSkillIds: template.skills.filter((id) => available.has(id)),
    autoLoadSkillIds: template.skills.filter((id) => available.has(id)),
    agentProfiles: template.profiles.map(profile),
    defaultAgentProfileId: template.profiles[0].id,
  };
  configureInstanceManagement(result, skills, template.management);
  return result;
}
