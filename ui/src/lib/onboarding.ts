import type { ExecutorConfig, LLMProvider, ModelEntry, ModelRouting } from '$lib/types/api';
import { isChatModel, isDecisionModel } from '$lib/providers';

export function executorReady(executor: ExecutorConfig): boolean {
  return executor.status === 'active' && executor.available
    && ['active', 'degraded'].includes(executor.runtime_state)
    && executor.desired_config_version === executor.applied_config_version
    && !!executor.observed_tools?.length;
}

export function modelReference(provider: LLMProvider, model: ModelEntry): string {
  return model.model_id.startsWith(`${provider.provider_id}/`)
    ? model.model_id : `${provider.provider_id}/${model.model_id}`;
}

/** Suggestions use actual discovered capabilities and literal upstream IDs. */
export function recommendedRoutes(provider: LLMProvider, current: ModelRouting): Record<string, { model: string }> {
  const models = provider.models;
  const chat = models.filter((model) => isChatModel(model) && model.supports_tools);
  const lite = chat.find((model) => model.model_id === 'openai/gpt-oss-20b');
  const smart = chat.find((model) => model.model_id === 'openai/gpt-oss-120b');
  const decision = models.find((model) => model.model_id === 'typesafe/jev-1.13' && isDecisionModel(model));
  const embedding = models.find((model) => model.supports_embedding && /(^|\/)text-embedding-3-small$/.test(model.model_id));
  const image = models.find((model) => model.supports_image_generation && /gemini.*image/.test(model.model_id))
    ?? models.find((model) => model.supports_image_generation);
  const suggestions: Record<string, ModelEntry | undefined> = {
    default: smart ?? lite,
    classifier: lite ?? smart,
    companion_lite: lite ?? smart,
    companion_smart: smart ?? lite,
    companion_embedding: embedding,
    intaris_evaluation: decision ?? lite,
    // Mirrors the validated production setup: memory extraction also uses 120B.
    mnemory_extraction: smart,
    mnemory_retrieval: smart,
    image_generation: image,
  };
  return Object.fromEntries(Object.entries(suggestions)
    .filter(([role, model]) => model && !current[role as keyof ModelRouting]?.model)
    .map(([role, model]) => [role, { model: modelReference(provider, model!) }]));
}

export function shellQuote(value: string): string {
  return `'${value.replaceAll("'", "'\\''")}'`;
}

export function executorWebsocketUrl(origin: string): string {
  const url = new URL(origin);
  if (!['http:', 'https:', 'ws:', 'wss:'].includes(url.protocol) || url.username || url.password) {
    throw new Error('Use an HTTP(S) controller URL without credentials.');
  }
  url.protocol = ['https:', 'wss:'].includes(url.protocol) ? 'wss:' : 'ws:';
  url.pathname = '/api/executor/ws';
  url.search = '';
  url.hash = '';
  return url.toString();
}

/** No token is embedded: copy it separately and enter it at the terminal prompt. */
export function executorInstallCommands(platform: string, origin: string): string {
  const url = executorWebsocketUrl(origin);
  if (platform === 'macos') {
    return `brew tap fpytloun/tap
brew install cognis-executor
cognis-executor configure --controller-url ${shellQuote(url)}
cognis-executor doctor --test-connection
brew services start cognis-executor
cognis-executor status`;
  }
  const connection = `printf 'Paste executor token: '
read -r COGNIS_EXECUTOR_TOKEN
export COGNIS_EXECUTOR_TOKEN
export COGNIS_CONTROLLER_URL=${shellQuote(url)}`;
  if (platform === 'kubernetes') {
    if (!url.startsWith('wss:')) throw new Error('Kubernetes needs a TLS controller URL reachable from the pod.');
    return `${connection}
kubectl create namespace cognis-executor
umask 077
envfile=$(mktemp)
printf 'COGNIS_EXECUTOR_TOKEN=%s\\nCOGNIS_CONTROLLER_URL=%s\\n' "$COGNIS_EXECUTOR_TOKEN" "$COGNIS_CONTROLLER_URL" > "$envfile"
kubectl -n cognis-executor create secret generic executor-connection --from-env-file="$envfile"
rm -f "$envfile"
unset COGNIS_EXECUTOR_TOKEN
kubectl -n cognis-executor apply -f - <<'YAML'
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: workspace
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 10Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: executor
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: cognis-executor
  template:
    metadata:
      labels:
        app: cognis-executor
    spec:
      automountServiceAccountToken: false
      securityContext:
        fsGroup: 1000
      containers:
        - name: executor
          image: ghcr.io/fpytloun/cognis-executor:latest
          envFrom:
            - secretRef:
                name: executor-connection
          env:
            - name: COGNIS_EXECUTOR_WORKDIR
              value: /home/cognis/workspace
          volumeMounts:
            - name: workspace
              mountPath: /home/cognis/workspace
      volumes:
        - name: workspace
          persistentVolumeClaim:
            claimName: workspace
YAML
kubectl -n cognis-executor rollout status deployment/executor
kubectl -n cognis-executor logs deployment/executor --tail=30`;
  }
  const network = url.startsWith('ws:') ? ' --network host' : '';
  if (url.startsWith('ws:') && !['localhost', '127.0.0.1', '[::1]'].includes(new URL(url).hostname)) {
    throw new Error('Non-loopback executors require HTTPS. Use TLS or Linux host networking with localhost.');
  }
  return `${connection}
docker volume create cognis-executor-data
docker run -d --name cognis-executor --restart unless-stopped${network} \\
  -e COGNIS_CONTROLLER_URL -e COGNIS_EXECUTOR_TOKEN \\
  -e COGNIS_EXECUTOR_WORKDIR=/home/cognis/workspace \\
  -v cognis-executor-data:/home/cognis \\
  ghcr.io/fpytloun/cognis-executor:latest
unset COGNIS_EXECUTOR_TOKEN
docker logs --tail=30 cognis-executor`;
}
