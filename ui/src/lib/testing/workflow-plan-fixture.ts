import type { Workflow } from '../types/api';

// Constructed health-check fixture; not a saved personal automation workflow.
export function syncHealthWorkflow(): Workflow {
  return {
    workflow_id: 'wf_synthetic_catalog_health',
    name: 'Sample Catalog Health',
    description: 'Synthetic catalog probe without AI work. Notify only when unhealthy; no real catalog is accessed.',
    version: 2,
    criteria: '',
    tags: ['catalog', 'synthetic', 'health'],
    interaction: { mode: 'none' },
    defaults: { max_attempts: 1, evaluate: false },
    is_system: false,
    owner_email: null,
    lifecycle: 'persistent',
    archived_at: null,
    lineage: null,
    editable_fields: [],
    has_overrides: false,
    disabled: false,
    disableable: false,
    override_warnings: [],
    steps: [
      {
        name: 'probe', type: 'tool_call', description: '',
        tool_call: {
          tool: 'bash',
          args: {
            command: 'printf \'{"healthy":true}\\n\'',
            description: 'Synthetic catalog health probe',
            target_executor: 'synthetic-catalog-executor',
          },
          allow_side_effects: true,
          timeout_seconds: 45,
        },
      },
      {
        name: 'route', type: 'condition', description: '',
        condition: { if: '{{ steps.probe.outputs.healthy == true }}', then: 'healthy', else: 'unhealthy' },
      },
      {
        name: 'unhealthy', type: 'complete', description: '',
        complete: {
          summary: 'The sample catalog requires attention.',
          content: 'Ukázkový katalog vyžaduje kontrolu. Ověřte pouze demonstrační záznamy.',
          outputs: { healthy: false },
          delivery_mode_override: 'preferred_channel',
        },
      },
      {
        name: 'healthy', type: 'complete', description: '',
        complete: {
          summary: 'The sample catalog is healthy.',
          outputs: { healthy: true },
          delivery_mode_override: 'silent',
        },
      },
    ],
  };
}
