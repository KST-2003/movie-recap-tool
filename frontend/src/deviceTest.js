import { capabilityTest, renderOnDevice } from './deviceRender.js';
const $ = (id) => document.getElementById(id), out = $('out');
const show = (o) => { out.textContent = typeof o === 'string' ? o : JSON.stringify(o, null, 2); if (new URLSearchParams(location.search).get('src')) document.title = typeof o === 'string' ? o : JSON.stringify(o); };
$('cap').onclick = async () => { show('Testing…'); try { show(await capabilityTest()); } catch (e) { show('Failed: ' + e.message); } };
$('go').onclick = async () => {
  const f = $('file').files[0];
  if (!f) return show('Pick a video first.');
  $('go').disabled = true; show('Rendering…');
  try {
    const { blob, stats } = await renderOnDevice(f, { onProgress: (p, t) => { $('bar').value = p; out.textContent = `${Math.round(p * 100)}%  ${t}`; } });
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
