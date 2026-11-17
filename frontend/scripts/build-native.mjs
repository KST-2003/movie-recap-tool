// Builds the web app for the Capacitor (iPhone / Android) shell into dist-app/.
// The normal build also carries the speech-removal and device-render TEST pages with their models (~230 MB): they stay out of the phone app.
// API address: VITE_API_BASE (default = the live server). For a local backend: VITE_API_BASE=http://localhost:8000 npm run build:native
import { execSync } from 'node:child_process';
import { cpSync, existsSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const api = process.env.VITE_API_BASE || 'https://movie-recap.bronicon.co';
console.log(`build-native: API = ${api}`);
execSync('npx vite build', { cwd: root, stdio: 'inherit', env: { ...process.env, VITE_API_BASE: api, VITE_NATIVE: '1' } });
const out = join(root, 'dist-app');
rmSync(out, { recursive: true, force: true });
const skip = new Set(['models', 'ort', 'device-test.html', 'separate-test.html']);
cpSync(join(root, 'dist'), out, { recursive: true, filter: (src) => !skip.has(src.slice(join(root, 'dist').length + 1).split('/')[0]) });
// the test pages' script bundles are tiny leftovers in assets/; harmless. Report the size.
if (existsSync(out)) console.log('build-native: dist-app ready');
