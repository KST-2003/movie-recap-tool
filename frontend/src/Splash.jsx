import React, { useEffect, useState } from 'react';
import '@fontsource/fredoka/700.css';
import '@fontsource/space-mono/400.css';
import { useI18n } from './i18n.jsx';

// Opening screen of the user app: the owner's design (docs/loading_screen.html: bouncing mascot, flying popcorn, 3D "Recat Studio").
// Shown for about 2 s when a signed-in user opens the app and right after signing in, then it fades away; the app loads underneath.
// A tap skips it; people who asked their device for less motion get a short still version.
const POPS = [[-90, -110, 200, 0], [95, -90, -160, 0.45], [-110, -20, 120, 0.9], [105, -150, 260, 1.35], [20, -170, -220, 0.7]];
const CSS = `
.sp-wrap{position:fixed;inset:0;z-index:100;display:flex;flex-direction:column;align-items:center;justify-content:center;overflow:hidden;
  background:radial-gradient(circle at 50% 40%,#3a2a6e,#140d2b);transition:opacity .45s ease,transform .45s ease}
.sp-wrap.sp-out{opacity:0;transform:scale(1.04);pointer-events:none}
.sp-stage{position:relative;width:240px;height:236px}
.sp-logo{position:absolute;left:20px;top:34px;width:200px;height:200px;animation:sp-bounce 1.2s cubic-bezier(.5,0,.5,1) infinite;transform-origin:50% 100%}
@keyframes sp-bounce{0%,100%{transform:translateY(0) scale(1.06,.94)}15%{transform:translateY(0) scale(1,1)}50%{transform:translateY(-34px) scale(.97,1.03) rotate(-3deg)}85%{transform:translateY(0) scale(1,1)}}
.sp-shadow{position:absolute;left:60px;bottom:-2px;width:120px;height:16px;border-radius:50%;background:rgba(0,0,0,.45);filter:blur(4px);animation:sp-sh 1.2s cubic-bezier(.5,0,.5,1) infinite}
@keyframes sp-sh{50%{transform:scale(.7);opacity:.5}}
.sp-pop{position:absolute;left:115px;top:150px;width:16px;height:14px;border-radius:50% 45% 50% 40%;background:radial-gradient(circle at 35% 35%,#fff9d6,#f7d35a);box-shadow:5px 3px 0 -1px #fbe38a,-4px 4px 0 -2px #fff3b8;opacity:0;animation:sp-pop 1.8s ease-out infinite}
@keyframes sp-pop{0%{opacity:0;transform:translate(0,0) scale(.3)}10%{opacity:1}100%{opacity:0;transform:translate(var(--x),var(--y)) rotate(var(--r)) scale(1)}}
.sp-txt{margin-top:18px;color:#f3e9ff;font-weight:600;letter-spacing:.08em;font-family:system-ui,sans-serif}
.sp-txt span{display:inline-block;animation:sp-dot 1.2s infinite}.sp-txt span:nth-child(2){animation-delay:.15s}.sp-txt span:nth-child(3){animation-delay:.3s}
@keyframes sp-dot{0%,60%,100%{transform:none;opacity:.4}30%{transform:translateY(-5px);opacity:1}}
.sp-brand{text-align:center;animation:sp-fade 1s ease-out both .2s;perspective:400px}
.sp-by{font-family:'Space Mono',monospace;font-size:11px;letter-spacing:.35em;text-transform:uppercase;color:rgba(243,233,255,.6)}
.sp-name{font-family:'Fredoka',system-ui,sans-serif;font-weight:700;font-size:44px;line-height:1;margin:6px 0 8px;color:#fffaf0;
  text-shadow:0 1px 0 #ffd1d6,0 2px 0 #ff9aa6,0 3px 0 #ff7a8a,0 4px 0 #f25a6c,0 5px 0 #e2475a,0 6px 0 #cf3449,0 7px 0 #b8263b,0 8px 0 #9e1c30,
  0 9px 2px rgba(0,0,0,.4),0 14px 12px rgba(0,0,0,.45),0 0 28px rgba(255,110,140,.35);animation:sp-tilt 4s ease-in-out infinite;transform-style:preserve-3d}
.sp-name b{color:#ffe27a;font-weight:700}
.sp-since{font-family:'Space Mono',monospace;font-size:10px;letter-spacing:.5em;color:rgba(243,233,255,.45)}
.sp-since:before,.sp-since:after{content:"";display:inline-block;width:26px;height:1px;background:rgba(243,233,255,.3);vertical-align:middle;margin:0 10px}
@keyframes sp-tilt{0%,100%{transform:rotateX(12deg) rotateY(-8deg)}50%{transform:rotateX(12deg) rotateY(8deg) translateY(-3px)}}
@keyframes sp-fade{from{opacity:0;transform:translateY(10px)}}
`;

export default function Splash({ ms = 2000, onDone }) {
  const { tr } = useI18n();
  const [out, setOut] = useState(false);
  useEffect(() => {
    const calm = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const t = setTimeout(() => setOut(true), calm ? 700 : ms);
    return () => clearTimeout(t);
  }, [ms]);
  useEffect(() => {
    if (!out) return undefined;
    const t = setTimeout(() => onDone?.(), 450);      // after the fade
    return () => clearTimeout(t);
  }, [out]);
  return (
    <div className={`sp-wrap ${out ? 'sp-out' : ''}`} role="status" aria-label={tr('Loading')} onClick={() => setOut(true)}>
      <style>{CSS}</style>
      <div className="sp-stage">
        {POPS.map(([x, y, r, d]) => <i key={d} className="sp-pop" style={{ '--x': `${x}px`, '--y': `${y}px`, '--r': `${r}deg`, animationDelay: `${d}s` }} />)}
        <div className="sp-shadow" />
        <img className="sp-logo" src="/recat.webp" alt="" />
      </div>
      <div className="sp-brand"><div className="sp-by">powered by</div><div className="sp-name">Recat <b>Studio</b></div><div className="sp-since">SINCE 2026</div></div>
      <div className="sp-txt">LOADING<span>.</span><span>.</span><span>.</span></div>
    </div>
  );
}
