import { deviceInfo, fetchModel, decodeAudio, separate, toWav } from './deviceSeparate.js';
import { separateLight, LIGHT_MODELS } from './deviceSeparateLight.js';

const $ = (id) => document.getElementById(id), out = $('out');
const q = new URLSearchParams(location.search);
const show = (o) => { out.textContent = typeof o === 'string' ? o : JSON.stringify(o, null, 2); };
const fail = (e) => 'Failed: ' + (e && e.message || e);

$('info').onclick = async () => { show('Checking…'); try { show(await deviceInfo()); } catch (e) { show(fail(e)); } };

// A crash (the browser reloads the page when it runs out of memory) leaves no error: remember the last step and show it next time.
const KEY = 'septest-last';
const mark = (step, extra) => { try { localStorage.setItem(KEY, JSON.stringify({ step, ...extra, at: new Date().toISOString() })); } catch (e) { /* private mode */ } };
const done = () => { try { localStorage.removeItem(KEY); } catch (e) { /* ignore */ } };
try {
  const last = JSON.parse(localStorage.getItem(KEY) || 'null');
  if (last) { show({ note: 'The last run on this device did not finish (the page was closed or reloaded, usually: out of memory).', stoppedAt: last.step, model: last.model, backend: last.backend, seconds: last.seconds, when: last.at }); done(); }
} catch (e) { /* ignore */ }

async function run(backend, file, seconds, which = 'light') {
  let lock = null;
  const ctx = { model: which, backend, seconds };
  try { lock = await navigator.wakeLock?.request('screen'); } catch (e) { /* not allowed: fine */ }
  try {
    mark('checking the device', ctx);
    const info = await deviceInfo();
    if (backend === 'webgpu' && !info.webgpu) throw new Error('This browser has no WebGPU. Try the CPU button.');
    show('Getting the model…'); mark('downloading the model', ctx);
    const urls = which === 'light' ? [LIGHT_MODELS.vocals, LIGHT_MODELS.accompaniment] : [undefined];
    const got = [];
    for (let k = 0; k < urls.length; k++) got.push(await fetchModel((p) => { $('bar').value = p; show(`Downloading the model… ${k + 1}/${urls.length}  ${Math.round(p * 100)}%`); }, urls[k]));
    show('Reading the sound of the video…'); mark('reading the sound of the video', ctx);
    const t0 = performance.now();
    const audio = await decodeAudio(file, seconds);
    const decodeSeconds = +((performance.now() - t0) / 1000).toFixed(1);
    show('Starting the model…'); mark('starting the model', ctx);
    const opts = {
      threads: Number(q.get('threads')) || undefined,
      onStage: (t) => mark(t, ctx),
      onProgress: (n, total, s) => { $('bar').value = n / total; show(`Removing speech… ${n}/${total} pieces, ${s.toFixed(0)} s`); mark(`after piece ${n} of ${total}`, ctx); },
    };
    const res = which === 'light'
      ? await separateLight(audio, { vocals: got[0].bytes, accompaniment: got[1].bytes }, backend, opts)
      : await separate(audio, got[0].bytes, backend, opts);
    mark('making the result playable', ctx);
    const stats = { ok: true, model: 'heavy (MDX-Net HQ_3)', ...res.stats, decodeSeconds, decoder: audio.decoder, modelWasCached: got[0].cached, sourceSeconds: +audio.sourceDuration.toFixed(1),
      device: { cpuThreads: info.cpuThreads, memoryHintGB: info.memoryHintGB, threadsAllowed: info.threadsAllowed, gpu: info.gpu, browser: info.browser } };
    const before = URL.createObjectURL(toWav(audio.left, audio.right)), blob = toWav(res.left, res.right), after = URL.createObjectURL(blob);
    $('a1').src = before; $('a2').src = after; $('dl').href = after;
    for (const id of ['a1', 'a2', 'l1', 'l2', 'dl']) $(id).hidden = false;
    $('bar').value = 1; show(stats); done();
    return { stats, blob };
  } catch (e) { done(); throw e; } finally { try { await lock?.release(); } catch (e) { /* ignore */ } }
}

async function press(backend) {
  const f = $('file').files[0];
  if (!f) return show('Pick a video first.');
  $('gpu').disabled = $('cpu').disabled = true;
  try { await run(backend, f, Number($('secs').value), $('model').value); } catch (e) { show(fail(e)); } finally { $('gpu').disabled = $('cpu').disabled = false; }
}
$('gpu').onclick = () => press('webgpu');
$('cpu').onclick = () => press('wasm');

// test helper: /separate-test.html?src=/clip.wav&backend=wasm|webgpu[&model=light|heavy][&secs=20][&threads=4][&upload=URL] runs at once; numbers end up in the page title
if (q.get('src')) {
  (async () => {
    try {
      const b = await (await fetch(q.get('src'))).blob();
      const { stats, blob } = await run(q.get('backend') || 'wasm', new File([b], 'clip', { type: b.type }), Number(q.get('secs') || 20), q.get('model') || 'light');
      if (q.get('upload')) await fetch(q.get('upload'), { method: 'POST', body: blob });
      document.title = 'RESULT ' + JSON.stringify(stats);
    } catch (e) { document.title = 'RESULT ' + JSON.stringify({ ok: false, error: String(e && e.message || e) }); show(fail(e)); }
  })();
}
