// Publishes a new WEB bundle to the phone apps over the air (no store release). Run from frontend/:  npm run ota:publish
// 1. builds the phone web app (same as `npm run build:native`), 2. zips dist-app, 3. uploads the zip to the server and writes latest.json
// (backend/ota.py serves it; apps pick it up the next time they come to the front and start it on the launch after).
// Env: OTA_SSH (default root@13.140.249.146), OTA_KEY (default ~/.ssh/id_moiorder), OTA_DIR (default /opt/movie-recap/data/ota),
//      OTA_MIN_BUILD_IOS / OTA_MIN_BUILD_ANDROID (lowest NATIVE build allowed to take it; raise when the bundle needs a newer native plugin),
//      VITE_API_BASE (default the live server). OTA_DISABLE=1 turns updates OFF (kill switch) without publishing anything.
import { execFileSync, execSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, rmSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const ssh = process.env.OTA_SSH || 'root@13.140.249.146';
const key = process.env.OTA_KEY || join(homedir(), '.ssh', 'id_moiorder');
const dir = process.env.OTA_DIR || '/opt/movie-recap/data/ota';
const sshArgs = ['-i', key];
const remote = (cmd) => execFileSync('ssh', [...sshArgs, ssh, cmd], { stdio: 'inherit' });

if (process.env.OTA_DISABLE === '1') {
  remote(`test -f ${dir}/latest.json && python3 -c "import json;p='${dir}/latest.json';d=json.load(open(p));d['enabled']=False;json.dump(d,open(p,'w'))" && echo 'OTA updates are OFF'`);
  process.exit(0);
}
execSync('node scripts/build-native.mjs', { cwd: root, stdio: 'inherit' });
const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 12);   // 202611171500
const version = `ota-${stamp}`;
const zip = join(root, `${version}.zip`);
rmSync(zip, { force: true });
execFileSync('zip', ['-qr', zip, '.'], { cwd: join(root, 'dist-app') });   // index.html at the top of the zip (what the plugin expects)
const checksum = createHash('sha256').update(readFileSync(zip)).digest('hex');
const latest = { version, file: `${version}.zip`, checksum, enabled: true, min_build: { ios: Number(process.env.OTA_MIN_BUILD_IOS || 1), android: Number(process.env.OTA_MIN_BUILD_ANDROID || 1) } };
console.log(`ota: ${version}  sha256 ${checksum.slice(0, 12)}…`);
remote(`mkdir -p ${dir}`);
execFileSync('scp', [...sshArgs, zip, `${ssh}:${dir}/${version}.zip`], { stdio: 'inherit' });
// latest.json is written AFTER the zip is there, so no app is told about a file that does not exist yet; old zips beyond the newest 5 are removed
remote(`chown -R recap:recap ${dir} && printf '%s' '${JSON.stringify(latest)}' > ${dir}/latest.json.tmp && chown recap:recap ${dir}/latest.json.tmp && mv ${dir}/latest.json.tmp ${dir}/latest.json && ls -1t ${dir}/ota-*.zip | tail -n +6 | xargs -r rm -f`);
rmSync(zip, { force: true });
console.log(`ota: published ${version}. Installed apps get it next time they come to the front, and run it from their next launch.`);
if (!existsSync(join(root, 'dist-app'))) process.exit(1);
