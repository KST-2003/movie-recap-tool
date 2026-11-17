import React from 'react';
import { ArrowRight, Heart as HeartIcon, Languages, Lock, Receipt } from 'lucide-react';
import { useLang } from '../lang.jsx';
import Reveal from '../components/Reveal.jsx';
import { Btn, Kernel, PageHead } from '../components/Bits.jsx';
import { FinalCta } from './Home.jsx';

const VALUE_ICONS = [Languages, HeartIcon, Receipt, Lock];
const VALUE_TINTS = ['bg-violet-100 text-violet-600', 'bg-pink-100 text-pink-600', 'bg-amber-100 text-amber-600', 'bg-emerald-100 text-emerald-600'];

export default function About() {
  const { c } = useLang();
  const a = c.about;
  return (
    <>
      <PageHead kicker={a.kicker} title={a.title}>{a.intro}</PageHead>

      <section className="px-4 py-10">
        <div className="mx-auto grid max-w-5xl items-center gap-10 md:grid-cols-[0.8fr_1.2fr]">
          <Reveal className="relative mx-auto w-64 sm:w-72">
            <div className="absolute inset-4 rounded-full bg-gradient-to-br from-lavender/60 to-blush/60 blur-2xl" aria-hidden="true" />
            <img src="/recat.webp" alt="Recat, our popcorn cat" className="relative animate-floaty drop-shadow-xl" width="288" height="288" />
            <Kernel size={30} className="absolute -left-2 top-6 animate-kernel" />
            <Kernel size={22} className="absolute -right-1 bottom-10 animate-kernel [animation-delay:-1.4s]" />
          </Reveal>
          <div className="flex flex-col gap-4">
            {a.story.map((s, i) => (
              <Reveal key={s.t} delay={i * 100} className="rounded-3xl bg-white p-6 shadow-card">
                <h2 className="font-display text-xl font-semibold">{s.t}</h2>
                <p className="mt-2 text-ink-soft">{s.d}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-white/60 px-4 py-16">
        <div className="mx-auto max-w-6xl">
          <Reveal className="mb-10 text-center"><h2 className="font-display text-3xl font-semibold sm:text-4xl">{a.valuesTitle}</h2></Reveal>
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {a.values.map((v, i) => {
              const Icon = VALUE_ICONS[i];
              return (
                <Reveal key={v.t} delay={i * 90} className="group rounded-3xl border border-violet-100 bg-page/70 p-6 hover:-translate-y-1.5 hover:bg-white hover:shadow-lift">
                  <div className={`grid h-12 w-12 place-items-center rounded-2xl ${VALUE_TINTS[i]} transition-transform duration-300 group-hover:rotate-6 group-hover:scale-110`}><Icon size={22} /></div>
                  <h3 className="mt-4 font-semibold">{v.t}</h3>
                  <p className="mt-1.5 text-sm text-ink-soft">{v.d}</p>
                </Reveal>
              );
            })}
          </div>
        </div>
      </section>

      <section className="px-4 py-16 text-center">
        <Reveal>
          <h2 className="font-display text-2xl font-semibold sm:text-3xl">{a.ctaTitle}</h2>
          <Btn to="/contact" className="mt-5">{a.ctaBtn}<ArrowRight size={16} /></Btn>
        </Reveal>
      </section>
      <FinalCta secondary={false} />
    </>
  );
}
