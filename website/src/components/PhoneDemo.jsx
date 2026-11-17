import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Mic, EyeOff, Scissors } from 'lucide-react';
import { useLang } from '../lang.jsx';
import { Heart, Sparkle } from './Bits.jsx';

// Splits Burmese into letter groups (a consonant with its vowel marks) so typing never shows half a letter.
const graphemes = (s) => {
  try { return Array.from(new Intl.Segmenter('my', { granularity: 'grapheme' }).segment(s), (x) => x.segment); } catch { return Array.from(s); }
};

const BARS = Array.from({ length: 26 }, (_, i) => i);

export default function PhoneDemo() {
  const { c } = useLang();
  const d = c.demo;
  const [line, setLine] = useState(0);
  const [shown, setShown] = useState(0);
  const wrap = useRef(null);
  const letters = useMemo(() => graphemes(d.burmese[line]), [d, line]);
  const reduce = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // type one letter group at a time, hold the full sentence, then move to the next one
  useEffect(() => {
    if (reduce) { setShown(letters.length); return undefined; }
    if (shown < letters.length) { const t = setTimeout(() => setShown(shown + 1), 45); return () => clearTimeout(t); }
    const t = setTimeout(() => { setLine((line + 1) % d.burmese.length); setShown(0); }, 2400);
    return () => clearTimeout(t);
  }, [shown, letters, line, d, reduce]);

  // gentle 3D tilt that follows the pointer (mouse only)
  const tilt = (e) => {
    if (reduce || e.pointerType !== 'mouse' || !wrap.current) return;
    const r = wrap.current.getBoundingClientRect();
    const x = (e.clientX - (r.left + r.width / 2)) / r.width;
    const y = (e.clientY - (r.top + r.height / 2)) / r.height;
    wrap.current.style.transform = `perspective(900px) rotateY(${(x * 10).toFixed(2)}deg) rotateX(${(-y * 8).toFixed(2)}deg)`;
  };
  const untilt = () => { if (wrap.current) wrap.current.style.transform = ''; };

  const chipCls = 'glass inline-flex items-center gap-2 rounded-full px-3.5 py-2 text-xs font-semibold text-ink shadow-card';
  const icons = [<Mic key="m" size={14} className="text-violet-600" />, <EyeOff key="e" size={14} className="text-pink-500" />, <Scissors key="s" size={14} className="text-amber-500" />];

  return (
    <div className="relative mx-auto w-[17rem] sm:w-[19rem]" onPointerMove={tilt} onPointerLeave={untilt}>
      {/* chips around the phone (wide screens) */}
      <div className="pointer-events-none absolute -left-24 top-16 z-30 hidden animate-floaty xl:block"><span className={chipCls}>{icons[0]}{d.chips[0]}</span></div>
      <div className="pointer-events-none absolute -right-16 top-1/2 z-30 hidden animate-floaty [animation-delay:-1.6s] xl:block"><span className={chipCls}>{icons[1]}{d.chips[1]}</span></div>
      <div className="pointer-events-none absolute -left-28 bottom-24 z-30 hidden animate-floaty [animation-delay:-3s] xl:block"><span className={chipCls}>{icons[2]}{d.chips[2]}</span></div>

      <div ref={wrap} className="relative transition-transform duration-200 ease-out will-change-transform">
        <div className="absolute inset-x-6 -bottom-6 h-10 rounded-[50%] bg-violet-500/25 blur-xl" aria-hidden="true" />
        <div className="relative rounded-[2.6rem] border-[9px] border-ink bg-ink shadow-lift">
          <div className="absolute left-1/2 top-2 z-30 h-4 w-20 -translate-x-1/2 rounded-full bg-ink" aria-hidden="true" />
          <div className="relative aspect-[9/18.5] overflow-hidden rounded-[2rem] bg-gradient-to-b from-indigo-500 via-violet-500 to-fuchsia-500">
            {/* the "film": drifting lights and a moon */}
            <div className="absolute -left-10 top-10 h-40 w-40 rounded-full bg-pink-300/60 blur-2xl animate-drift" />
            <div className="absolute -right-10 top-40 h-44 w-44 rounded-full bg-sky-300/50 blur-2xl animate-drift [animation-delay:-5s]" />
            <div className="absolute right-8 top-16 h-14 w-14 rounded-full bg-amber-100 shadow-[0_0_40px_10px_rgba(255,236,179,0.6)]" />
            <div className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-ink/80 to-transparent" />
            <div className="absolute inset-y-0 w-1/3 -skew-x-12 bg-white/15 blur-md animate-sweep" aria-hidden="true" />

            {/* a creator's corner watermark, hidden */}
            <div className="absolute left-3 top-8 rounded-md bg-white/10 px-2 py-1 text-[10px] font-semibold text-white/80 backdrop-blur-md">@creator<span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-white/70" /></div>
            <div className="absolute right-3 top-8 flex items-center gap-1 rounded-full bg-black/30 px-2 py-1 text-[9px] font-semibold uppercase tracking-wide text-white backdrop-blur-sm"><span className="h-1.5 w-1.5 animate-blink rounded-full bg-rose-400" />{d.live}</div>

            {/* Burmese subtitle */}
            <div className="absolute inset-x-3 bottom-[5.2rem] flex min-h-[3.6rem] items-center justify-center rounded-xl bg-black/55 px-2.5 py-2 text-center backdrop-blur-sm" aria-live="off">
              <p lang="my" className="text-[12.5px] font-semibold leading-[1.75] text-amber-300 sm:text-[13.5px]">
                {letters.slice(0, shown).join('')}<span className="ml-0.5 inline-block h-3.5 w-[2px] translate-y-0.5 animate-blink bg-amber-300" />
              </p>
            </div>

            {/* the original Chinese subtitle, blurred */}
            <div className="absolute inset-x-3 bottom-12 rounded-lg px-2 py-1.5 text-center">
              <p className="select-none text-[11px] font-medium text-white/90 blur-[3.5px]" aria-hidden="true">{d.source[line]}</p>
              <div className="absolute inset-0 rounded-lg bg-white/15 backdrop-blur-md" aria-hidden="true" />
            </div>

            {/* voice waveform + play bar */}
            <div className="absolute inset-x-4 bottom-4 flex flex-col gap-2">
              <div className="flex h-5 items-center justify-center gap-[3px]" aria-hidden="true">
                {BARS.map((b) => <span key={b} className="h-full w-[3px] origin-center rounded-full bg-white/85 animate-bar" style={{ animationDelay: `${(b % 9) * 0.11}s`, animationDuration: `${0.8 + (b % 5) * 0.14}s` }} />)}
              </div>
              <div className="h-1 overflow-hidden rounded-full bg-white/25"><div key={line} className="h-full rounded-full bg-gradient-to-r from-amber-300 to-pink-300 [animation:grow_4.4s_linear_forwards]" /></div>
            </div>
          </div>
        </div>
        {/* cat sticker peeking over the phone */}
        <img src="/recat.webp" alt="" className="absolute -bottom-7 -right-10 z-20 w-24 animate-floaty drop-shadow-xl sm:-right-12 sm:w-28" width="112" height="112" />
        <Heart className="absolute -right-2 bottom-24 z-20 animate-heart" />
        <Heart className="absolute right-6 bottom-28 z-20 animate-heart [animation-delay:-1.4s]" size={16} />
        <Sparkle className="absolute -left-5 top-24 animate-kernel" />
      </div>

      {/* chips under the phone (small screens) */}
      <div className="mt-12 flex flex-wrap justify-center gap-2 xl:hidden">
        {d.chips.map((t, i) => <span key={t} className={chipCls}>{icons[i]}{t}</span>)}
      </div>
    </div>
  );
}
