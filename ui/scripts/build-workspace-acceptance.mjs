// Build the real packaged app, including its root auth/workspace/bridge owners,
// with one temporary test-only route. This export must never be installed.
import { copyFile, mkdir, rm, access, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
const route = 'src/routes/workspace-acceptance';
try { await access(route); throw new Error('Refusing to overwrite an existing route'); }
catch (error) { if (error.code !== 'ENOENT') throw error; }
await mkdir(route);
try {
  await copyFile('src/acceptance/workspace/+page.svelte', `${route}/+page.svelte`);
  for (const args of [['svelte-kit', 'sync'], ['vite', 'build', '--config', 'vite.workspace-acceptance.config.ts']]) {
    const result = spawnSync('npx', args, { env: { ...process.env, COGNIS_APPLE_BUNDLE: '1' }, stdio: 'inherit' });
    if (result.status !== 0) throw new Error(`Fixture export failed: ${args.join(' ')}`);
  }
  await writeFile('build-apple/WORKSPACE_ACCEPTANCE_ONLY', 'Test-only application export. Do not install.\n');
} finally {
  await rm(route, { recursive: true, force: true });
}
