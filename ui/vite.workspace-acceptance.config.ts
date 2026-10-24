// Test-only export: preserve caller names without changing normal builds.
import { mergeConfig } from 'vite';
import config from './vite.config';
export default mergeConfig(config, { build: { minify: false } });
