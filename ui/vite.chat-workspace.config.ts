import { mergeConfig } from 'vite';
import config from './vite.window-drag.config';

export default mergeConfig(config, { cacheDir: 'node_modules/.vite-chat-workspace' });
