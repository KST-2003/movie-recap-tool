// Copies the onnxruntime-web runtime files into public/ort/ (not in git) so /separate-test.html can load them from our own domain.
import { cpSync, mkdirSync, readdirSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const src = join(root, 'node_modules', 'onnxruntime-web', 'dist');
const dst = join(root, 'public', 'ort');
if (!existsSync(src)) { console.log('copy-ort: onnxruntime-web is not installed, skipped'); process.exit(0); }
mkdirSync(dst, { recursive: true });
let n = 0;
for (const f of readdirSync(src)) {
  if (/^ort-wasm-simd-threaded\..*(wasm|mjs)$/.test(f) || f === 'ort.webgpu.min.mjs') { cpSync(join(src, f), join(dst, f)); n++; }
}
console.log(`copy-ort: ${n} files -> public/ort/`);
