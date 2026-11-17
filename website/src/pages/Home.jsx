import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Check, ChevronDown, Clapperboard, Crop, Download, EyeOff, Link2, MessageSquare, Mic, Palette, SlidersHorizontal, Smartphone, Wand2 } from 'lucide-react';
import { useLang } from '../lang.jsx';
import { SITE } from '../site.config.js';
import Reveal, { Counter } from '../components/Reveal.jsx';
import PhoneDemo from '../components/PhoneDemo.jsx';
import { Blobs, Btn, Heart, Kernel, Sparkle } from '../components/Bits.jsx';

// popcorn kernels scattered behind the hero: [left %, top %, size, delay s]
const KERNELS = [[6, 22, 30, 0], [44, 12, 24, 1.2], [90, 18, 34, 0.6], [52, 80, 26, 2], [3, 70, 36, 1.6], [94, 66, 24, 0.3]];

function Hero() {
  const { c } = useLang();
  const h = c.hero;
  return (
    <section className="relative overflow-hidden px-4 pb-20 pt-28 sm:pt-32 lg:pt-36">
      <Blobs />
      <div className="dots pointer-events-none absolute inset-0 opacity-60 [mask-image:radial-gradient(ellipse_at_center,black,transparent_70%)]" aria-hidden="true" />
      {KERNELS.map(([l, t, s, d], i) => <Kernel key={i} size={s} className="absolute animate-kernel opacity-80 max-sm:opacity-30" style={{ left: `${l}%`, top: `${t}%`, animationDelay: `${d}s` }} />)}
      <div className="relative mx-auto grid max-w-6xl items-center gap-14 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="text-center lg:text-left">
          <span className="page-in inline-flex items-center gap-2 rounded-full bg-white/85 px-4 py-1.5 text-xs font-semibold text-violet-700 shadow-card">
            <Sparkle size={14} />{h.badge}
          </span>
          <h1 className="page-in mt-5 font-display text-[2.6rem] font-semibold leading-[1.12] tracking-tight [animation-delay:80ms] sm:text-6xl">
            {h.title}<br /><span className="text-candy animate-shimmer">{h.accent}</span>
          </h1>
          <p className="page-in mx-auto mt-5 max-w-xl text-base text-ink-soft [animation-delay:160ms] sm:text-lg lg:mx-0">{h.sub}</p>
          <div className="page-in mt-7 flex flex-col items-center gap-3 [animation-delay:240ms] sm:flex-row sm:justify-center lg:justify-start">
            <Btn href={SITE.appUrl} external className="w-full sm:w-auto">{h.cta1}<ArrowRight size={16} /></Btn>
            <Btn to="/#how" variant="ghost" className="w-full sm:w-auto">{h.cta2}</Btn>
          </div>
          <ul className="page-in mt-8 flex flex-wrap justify-center gap-x-6 gap-y-2 text-sm text-ink-soft [animation-delay:320ms] lg:justify-start">
            {h.points.map((p) => <li key={p} className="inline-flex items-center gap-1.5"><span className="grid h-5 w-5 place-items-center rounded-full bg-emerald-100 text-emerald-600"><Check size={12} strokeWidth={3} /></span>{p}</li>)}
          </ul>
        </div>
        <div className="page-in [animation-delay:200ms]"><PhoneDemo /></div>
      </div>
    </section>
  );
}

function Sources() {
  const { c } = useLang();
  const items = [...c.sources.items, ...c.sources.items, ...c.sources.items, ...c.sources.items];
  return (
    <section className="relative border-y border-violet-100 bg-white/70 py-6" aria-label={c.sources.title}>
      <div className="mx-auto mb-4 max-w-6xl px-4 text-center text-xs font-semibold uppercase tracking-wider text-ink-faint">{c.sources.title}</div>
      <div className="overflow-hidden [mask-image:linear-gradient(90deg,transparent,black_12%,black_88%,transparent)]">
        <div className="flex w-max animate-marquee gap-4 hover:[animation-play-state:paused]">
          {items.map((t, i) => <span key={i} className="whitespace-nowrap rounded-full border border-violet-100 bg-violet-50/70 px-5 py-2 text-sm font-medium text-violet-700">{t}</span>)}
        </div>
      </div>
    </section>
  );
}

function SectionTitle({ kicker, title, sub }) {
  return (
    <Reveal className="mx-auto mb-12 max-w-2xl text-center">
      <span className="text-xs font-semibold uppercase tracking-wider text-violet-500">{kicker}</span>
      <h2 className="mt-2 font-display text-3xl font-semibold leading-tight sm:text-4xl">{title}</h2>
      {sub && <p className="mt-3 text-ink-soft">{sub}</p>}
    </Reveal>
  );
}

const STEP_ICONS = [Link2, Wand2, SlidersHorizontal, Download];
const STEP_COLORS = ['from-violet-400 to-violet-600', 'from-fuchsia-400 to-pink-500', 'from-amber-300 to-orange-400', 'from-sky-400 to-indigo-500'];

function How() {
  const { c } = useLang();
  return (
    <section id="how" className="relative scroll-mt-20 px-4 py-20">
      <div className="mx-auto max-w-6xl">
        <SectionTitle kicker={c.how.kicker} title={c.how.title} />
        <div className="relative grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          <div className="pointer-events-none absolute left-[12%] right-[12%] top-12 hidden h-0.5 border-t-2 border-dashed border-violet-200 lg:block" aria-hidden="true" />
          {c.how.steps.map((s, i) => {
            const Icon = STEP_ICONS[i];
            return (
              <Reveal key={s.t} delay={i * 110} className="group relative rounded-3xl bg-white p-6 shadow-card hover:-translate-y-1.5 hover:shadow-lift">
                <div className={`relative grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br ${STEP_COLORS[i]} text-white shadow-pop transition-transform duration-300 group-hover:rotate-6 group-hover:scale-110`}>
                  <Icon size={24} />
                  <span className="absolute -right-2 -top-2 grid h-6 w-6 place-items-center rounded-full bg-white text-xs font-bold text-violet-600 shadow-card">{i + 1}</span>
                </div>
                <h3 className="mt-4 text-lg font-semibold">{s.t}</h3>
                <p className="mt-1.5 text-sm text-ink-soft">{s.d}</p>
              </Reveal>
            );
          })}
        </div>
      </div>
    </section>
  );
}

const FEATURE_ICONS = [Mic, MessageSquare, EyeOff, SlidersHorizontal, Clapperboard, Smartphone, Crop, Palette];
const FEATURE_TINTS = ['bg-violet-100 text-violet-600', 'bg-pink-100 text-pink-600', 'bg-sky-100 text-sky-600', 'bg-amber-100 text-amber-600', 'bg-fuchsia-100 text-fuchsia-600', 'bg-emerald-100 text-emerald-600', 'bg-indigo-100 text-indigo-600', 'bg-rose-100 text-rose-600'];

function Features() {
  const { c } = useLang();
  return (
    <section id="features" className="relative scroll-mt-20 bg-white/60 px-4 py-20">
      <div className="mx-auto max-w-6xl">
        <SectionTitle kicker={c.features.kicker} title={c.features.title} />
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {c.features.items.map((f, i) => {
            const Icon = FEATURE_ICONS[i];
            return (
              <Reveal key={f.t} delay={(i % 4) * 90} className="group rounded-3xl border border-violet-100 bg-page/70 p-6 hover:-translate-y-1.5 hover:border-violet-200 hover:bg-white hover:shadow-lift">
                <div className={`grid h-12 w-12 place-items-center rounded-2xl ${FEATURE_TINTS[i]} transition-transform duration-300 group-hover:-rotate-6 group-hover:scale-110`}><Icon size={22} /></div>
                <h3 className="mt-4 font-semibold">{f.t}</h3>
                <p className="mt-1.5 text-sm text-ink-soft">{f.d}</p>
              </Reveal>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function Stats() {
  const { c } = useLang();
  return (
    <section className="px-4 py-16">
      <Reveal className="relative mx-auto max-w-6xl overflow-hidden rounded-[2rem] bg-gradient-to-br from-violet-600 via-violet-500 to-fuchsia-500 px-6 py-12 text-white shadow-lift">
        <Kernel size={40} className="absolute left-6 top-4 hidden animate-kernel opacity-70 sm:block" />
        <Heart className="absolute bottom-6 right-8 animate-floaty opacity-80" size={30} />
        <div className="relative grid grid-cols-2 gap-8 text-center lg:grid-cols-4">
          {c.stats.map((s) => (
            <div key={s.l}>
              <div className="font-display text-5xl font-semibold sm:text-6xl"><Counter to={s.n} suffix={s.s} /></div>
              <div className="mt-1 text-sm text-white/85">{s.l}</div>
            </div>
          ))}
        </div>
      </Reveal>
    </section>
  );
}

function PriceTeaser() {
  const { c } = useLang();
  const p = c.priceTeaser;
  return (
    <section className="px-4 py-16">
      <div className="mx-auto grid max-w-6xl items-center gap-8 rounded-[2rem] bg-white p-8 shadow-card md:grid-cols-[1fr_auto] md:p-12">
        <Reveal>
          <span className="text-xs font-semibold uppercase tracking-wider text-violet-500">{p.kicker}</span>
          <h2 className="mt-2 font-display text-3xl font-semibold sm:text-4xl">{p.title}</h2>
          <p className="mt-3 max-w-xl text-ink-soft">{p.sub}</p>
          <div className="mt-5 flex flex-wrap items-end gap-x-3 gap-y-1">
            <span className="text-sm text-ink-soft">{p.from}</span>
            <span className="text-candy animate-shimmer font-display text-6xl font-semibold leading-none">{SITE.pricePerMinuteTHB}</span>
            <span className="pb-1 text-sm text-ink-soft">{p.per}</span>
          </div>
          <Btn to="/pricing" className="mt-6">{p.cta}<ArrowRight size={16} /></Btn>
        </Reveal>
        <Reveal delay={150} className="hidden justify-self-center md:block">
          <img src="/recat.webp" alt="" className="w-56 animate-floaty drop-shadow-xl" width="224" height="224" loading="lazy" />
        </Reveal>
      </div>
    </section>
  );
}

function Faq() {
  const { c } = useLang();
  const [open, setOpen] = useState(0);
  return (
    <section id="faq" className="scroll-mt-20 px-4 py-20">
      <div className="mx-auto max-w-3xl">
        <SectionTitle kicker={c.faq.kicker} title={c.faq.title} />
        <div className="flex flex-col gap-3">
          {c.faq.items.map((f, i) => {
            const isOpen = open === i;
            return (
              <Reveal key={f.q} delay={i * 50} className={`overflow-hidden rounded-2xl border bg-white shadow-card ${isOpen ? 'border-violet-300' : 'border-violet-100'}`}>
                <button className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left font-semibold" onClick={() => setOpen(isOpen ? -1 : i)} aria-expanded={isOpen}>
                  {f.q}
                  <ChevronDown size={20} className={`shrink-0 text-violet-500 transition-transform duration-300 ${isOpen ? 'rotate-180' : ''}`} />
                </button>
                <div className={`grid transition-[grid-template-rows] duration-300 ease-out ${isOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
                  <div className="overflow-hidden"><p className="px-5 pb-5 text-ink-soft">{f.a}</p></div>
                </div>
              </Reveal>
            );
          })}
        </div>
      </div>
    </section>
  );
}

export function FinalCta({ secondary = true }) {
  const { c } = useLang();
  return (
    <section className="px-4 pb-20 pt-6">
      <Reveal className="relative mx-auto max-w-5xl overflow-hidden rounded-[2.2rem] bg-gradient-to-br from-violet-600 via-violet-500 to-pink-500 px-6 py-14 text-center text-white shadow-lift sm:px-12">
        <div className="pointer-events-none absolute -left-10 -top-10 h-48 w-48 rounded-full bg-white/15 blur-2xl" aria-hidden="true" />
        <div className="pointer-events-none absolute -bottom-12 -right-10 h-56 w-56 rounded-full bg-popcorn/30 blur-2xl" aria-hidden="true" />
        <img src="/recat-thanks.webp" alt="" className="relative mx-auto h-32 w-32 animate-wiggle drop-shadow-xl sm:h-36 sm:w-36" width="144" height="144" loading="lazy" />
        <h2 className="relative mx-auto mt-3 max-w-2xl font-display text-3xl font-semibold leading-tight sm:text-4xl">{c.cta.title}</h2>
        <p className="relative mx-auto mt-3 max-w-xl text-white/90">{c.cta.sub}</p>
        <div className="relative mt-7 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <a href={SITE.appUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-full bg-white px-6 py-3 text-sm font-semibold text-violet-700 shadow-pop hover:-translate-y-0.5 hover:shadow-lift">{c.cta.btn}<ArrowRight size={16} /></a>
          {secondary && <Link to="/contact" className="inline-flex items-center gap-2 rounded-full border border-white/50 px-6 py-3 text-sm font-semibold text-white hover:bg-white/15">{c.cta.ask}</Link>}
        </div>
      </Reveal>
    </section>
  );
}

export default function Home() {
  return <><Hero /><Sources /><How /><Features /><Stats /><PriceTeaser /><Faq /><FinalCta /></>;
}
