import React from 'react';
import { Check, QrCode, ShieldCheck, Sparkles } from 'lucide-react';
import { useLang } from '../lang.jsx';
import { SITE } from '../site.config.js';
import Reveal, { Counter } from '../components/Reveal.jsx';
import { Btn, PageHead } from '../components/Bits.jsx';

export default function Pricing() {
  const { c } = useLang();
  const p = c.pricing;
  return (
    <>
      <PageHead kicker={p.kicker} title={p.title}>{p.intro}</PageHead>

      <section className="px-4 py-6">
        <div className="mx-auto max-w-5xl">
          <Reveal className="mx-auto mb-10 w-fit rounded-[2rem] bg-white px-10 py-7 text-center shadow-card">
            <div className="text-candy animate-shimmer font-display text-7xl font-semibold leading-none"><Counter to={SITE.pricePerMinuteTHB} /></div>
            <div className="mt-2 text-sm text-ink-soft">{p.priceLabel}</div>
          </Reveal>

          <Reveal className="mb-6 text-center">
            <h2 className="font-display text-2xl font-semibold sm:text-3xl">{p.packsTitle}</h2>
            <p className="mx-auto mt-2 max-w-xl text-sm text-ink-soft">{p.packsSub}</p>
          </Reveal>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {SITE.packs.map((m, i) => (
              <Reveal key={m} delay={i * 90} className={`group relative rounded-3xl p-6 text-center hover:-translate-y-1.5 hover:shadow-lift ${i === 2 ? 'bg-gradient-to-br from-violet-600 to-fuchsia-500 text-white shadow-pop' : 'bg-white shadow-card'}`}>
                {i === 2 && <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-popcorn px-3 py-1 text-[11px] font-bold text-ink"><Sparkles size={11} className="mr-1 inline" />{p.popular}</span>}
                <div className="font-display text-4xl font-semibold">{m}</div>
                <div className={`text-sm ${i === 2 ? 'text-white/85' : 'text-ink-soft'}`}>{p.minutes}</div>
                <div className={`mt-4 text-2xl font-semibold ${i === 2 ? '' : 'text-violet-700'}`}>{m * SITE.pricePerMinuteTHB} <span className="text-sm font-medium">THB</span></div>
              </Reveal>
            ))}
          </div>
          <Reveal className="mx-auto mt-6 flex max-w-2xl items-start gap-3 rounded-2xl bg-white/80 p-4 text-sm text-ink-soft shadow-card">
            <QrCode size={20} className="mt-0.5 shrink-0 text-violet-600" />{p.approve}
          </Reveal>
        </div>
      </section>

      <section className="px-4 py-14">
        <div className="mx-auto max-w-5xl">
          <Reveal className="mb-8 text-center"><h2 className="font-display text-2xl font-semibold sm:text-3xl">{p.howTitle}</h2></Reveal>
          <ol className="grid gap-5 md:grid-cols-3">
            {p.how.map((s, i) => (
              <Reveal as="li" key={s.t} delay={i * 110} className="rounded-3xl bg-white p-6 shadow-card">
                <span className="grid h-9 w-9 place-items-center rounded-full bg-violet-100 font-display font-semibold text-violet-700">{i + 1}</span>
                <h3 className="mt-3 font-semibold">{s.t}</h3>
                <p className="mt-1.5 text-sm text-ink-soft">{s.d}</p>
              </Reveal>
            ))}
          </ol>
        </div>
      </section>

      <section className="bg-white/60 px-4 py-14">
        <div className="mx-auto max-w-4xl">
          <Reveal className="mb-8 text-center"><h2 className="font-display text-2xl font-semibold sm:text-3xl">{p.qualityTitle}</h2></Reveal>
          <div className="grid gap-5 md:grid-cols-2">
            {[p.std, p.high].map((q, i) => (
              <Reveal key={q.t} delay={i * 110} className="rounded-3xl border border-violet-100 bg-page/70 p-6 hover:-translate-y-1 hover:bg-white hover:shadow-lift">
                <div className="flex items-center gap-2 font-display text-xl font-semibold"><span className="grid h-7 w-7 place-items-center rounded-full bg-emerald-100 text-emerald-600"><Check size={15} strokeWidth={3} /></span>{q.t}</div>
                <p className="mt-2 text-sm text-ink-soft">{q.d}</p>
              </Reveal>
            ))}
          </div>
          <Reveal className="mt-6 flex items-start gap-3 rounded-2xl bg-amber-50 p-4 text-sm text-amber-800">
            <ShieldCheck size={20} className="mt-0.5 shrink-0" />{p.note}
          </Reveal>
        </div>
      </section>

      <section className="px-4 py-16 text-center"><Reveal><Btn to="/contact">{p.cta}</Btn></Reveal></section>
    </>
  );
}
