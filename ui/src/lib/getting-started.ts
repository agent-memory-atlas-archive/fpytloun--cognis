import type { SystemDiagnostics } from '$lib/types/api';

export interface GettingStartedStep {
  id: string;
  label: string;
  description: string;
  href: string;
  done: boolean;
}

export function deriveGettingStartedSteps(diagnostics: SystemDiagnostics): GettingStartedStep[] {
  const readiness = diagnostics.readiness ?? {};
  return [
    {
      id: 'services',
      label: 'Check companion services',
      description: 'Make sure Mnemory and Intaris are reachable from Cognis.',
      href: '/settings?tab=system',
      done: Boolean(readiness.mnemory_reachable && readiness.intaris_reachable)
    },
    {
      id: 'providers',
      label: 'Configure LLM provider',
      description: 'Choose an agent model with tool calling. OpenRouter can also cover companion and image models.',
      href: '/settings?tab=providers',
      done: Boolean(readiness.agent_model_configured)
    },
    {
      id: 'routing',
      label: 'Configure Intaris and Mnemory models',
      description: 'Set Lite, Smart, and Embedding models; optionally use Jev for Intaris evaluation.',
      href: '/settings?tab=routing',
      done: Boolean(readiness.companion_routes_configured)
    },
    {
      id: 'images',
      label: 'Enable image generation (recommended)',
      description: 'Optional: generate an avatar when creating your agent.',
      href: '/settings?tab=routing',
      done: Boolean(readiness.image_generation_configured)
    },
    {
      id: 'executor',
      label: 'Connect an executor',
      description: 'Install and connect an executor before creating an agent. Check that tools are observed and configuration is applied.',
      href: '/settings?tab=executors',
      done: Boolean(readiness.executor_tools_configured)
    },
    {
      id: 'agents',
      label: 'Create your first agent',
      description: 'Start from the XO template to manage Cognis and create specialists through conversation.',
      href: '/agents/new?template=xo&onboarding=1',
      done: Boolean(readiness.agent_created)
    },
    {
      id: 'chat',
      label: 'Start chatting',
      description: 'Verify a tool call, memory recall, and creating a specialist from the XO owner chat.',
      href: '/chat/new',
      done: Boolean(readiness.chat_ready)
    }
  ];
}

export function shouldOfferOnboarding(diagnostics: SystemDiagnostics): boolean {
  return diagnostics.readiness.onboarding_pending === true
    && !diagnostics.readiness.chat_ready;
}
