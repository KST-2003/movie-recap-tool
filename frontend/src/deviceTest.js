import { capabilityTest, renderOnDevice, speedLab } from './deviceRender.js';
import { renderFromPlan } from './deviceRenderPlan.js';
const $ = (id) => document.getElementById(id), out = $('out');
const retry = async (fn) => { try { return await fn(); } catch (e) { out.textContent = 'First try failed (' + (e && e.message || e) + '), trying again…'; return await fn(); } };   // the first run after picking a file sometimes fails on iPhone
const show = (o) => { out.textContent = typeof o === 'string' ? o : JSON.stringify(o, null, 2); if (new URLSearchParams(location.search).get('src')) document.title = typeof o === 'string' ? o : JSON.stringify(o); };
$('cap').onclick = async () => { show('Testing…'); try { show(await capabilityTest()); } catch (e) { show('Failed: ' + e.message); } };
$('lab').onclick = async () => {
  const f = $('file').files[0];
  if (!f) return show('Pick a video first.');
  $('lab').disabled = true;
  try { const lines = []; const res = await retry(() => speedLab(f, 15, (t) => { lines.push(t); out.textContent = lines.join('\n'); })); show(res); } catch (e) { show('Failed: ' + (e && e.message || e)); } finally { $('lab').disabled = false; }
};
$('go').onclick = async () => {
  const f = $('file').files[0];
  if (!f) return show('Pick a video first.');
  $('go').disabled = true; show('Rendering…');
  try {
    const { blob, stats } = await retry(() => renderOnDevice(f, { onProgress: (p, t) => { $('bar').value = p; out.textContent = `${Math.round(p * 100)}%  ${t}`; } }));
    $('bar').value = 1; show(stats);
    const url = URL.createObjectURL(blob);
    $('vid').src = url; $('vid').hidden = false; $('dl').href = url; $('dl').hidden = false;
  } catch (e) { show('Failed: ' + (e && e.message || e)); } finally { $('go').disabled = false; }
};

// test helper: /device-test.html?src=/clip.mp4 renders that file straight away and leaves the numbers in window.__result
const srcParam = new URLSearchParams(location.search).get('src');
if (srcParam) {
  (async () => {
    try {
      show('Capability test…'); const cap = await capabilityTest(); window.__capability = cap;
      const blob = await (await fetch(srcParam)).blob();
      const { stats, blob: result } = await renderOnDevice(new File([blob], 'clip.mp4', { type: blob.type }));
      const up = new URLSearchParams(location.search).get('upload');   // test helper: send the result to a local receiver so it can be inspected with ffprobe
      if (up) await fetch(up, { method: 'POST', body: result });
      window.__result = { cap, stats }; show(window.__result);
    } catch (e) { window.__result = { error: String(e && e.message || e) }; show(window.__result); }
  })();
}

if (new URLSearchParams(location.search).get('lab')) {   // test helper: /device-test.html?lab=/clip.mp4 runs the speed lab at once
  (async () => { try { const blob = await (await fetch(new URLSearchParams(location.search).get('lab'))).blob();
    const res = await speedLab(new File([blob], 'clip.mp4', { type: blob.type }), 15); document.title = JSON.stringify(res); show(res); } catch (e) { document.title = 'error ' + e; } })();
}

// test helper: /device-test.html?plan=/plan.json&audio=/voice.m4a&video=/clip.mp4[&upload=URL] renders from a server plan
{
  const q = new URLSearchParams(location.search);
  if (q.get('plan')) {
    (async () => {
      try {
        const plan = await (await fetch(q.get('plan'))).json();
        const audio = await (await fetch(q.get('audio'))).blob(), vb = await (await fetch(q.get('video'))).blob();
        const { blob, stats } = await renderFromPlan(new File([vb], 'clip.mp4', { type: vb.type }), plan, audio, null, {});
        if (q.get('upload')) await fetch(q.get('upload'), { method: 'POST', body: blob });
        document.title = JSON.stringify(stats); show(stats);
      } catch (e) { document.title = 'error ' + (e && e.message || e); show(document.title); }
    })();
  }
}
