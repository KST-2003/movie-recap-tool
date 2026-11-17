import React, { useState } from 'react';
import { Clock, Facebook, Mail, MessageCircle, Phone, Send } from 'lucide-react';
import { useLang } from '../lang.jsx';
import { SITE } from '../site.config.js';
import Reveal from '../components/Reveal.jsx';
import { PageHead } from '../components/Bits.jsx';

const field = 'w-full rounded-2xl border border-violet-100 bg-white px-4 py-3 text-sm placeholder:text-ink-faint focus:border-violet-400 focus:outline-none focus:ring-2 focus:ring-violet-200';

export default function Contact() {
  const { c } = useLang();
  const t = c.contact;
  const { email, telegram, facebook, phone, hours } = SITE.contact;
  const [f, setF] = useState({ name: '', email: '', topic: 0, message: '' });
  const [msg, setMsg] = useState('');
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const channels = [
    email && { icon: Mail, label: t.labels.email, text: email, href: `mailto:${email}` },
    telegram && { icon: MessageCircle, label: t.labels.telegram, text: telegram.replace(/^https?:\/\//, ''), href: telegram },
    facebook && { icon: Facebook, label: t.labels.facebook, text: facebook.replace(/^https?:\/\//, ''), href: facebook },
    phone && { icon: Phone, label: t.labels.phone, text: phone, href: `tel:${phone.replace(/\s+/g, '')}` },
    hours && { icon: Clock, label: t.labels.hours, text: hours },
  ].filter(Boolean);

  const submit = (e) => {
    e.preventDefault();
    if (!f.email.trim() || !f.message.trim()) { setMsg(t.required); return; }
    if (!email) return;   // the form is hidden without an email address; nothing to open
    const subject = `${SITE.name}: ${t.topics[f.topic]}`;
    const body = `${f.message}\n\n— ${f.name || '-'} (${f.email})`;
    setMsg(t.thanks);
    window.location.href = `mailto:${email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  };

  return (
    <>
      <PageHead kicker={t.kicker} title={t.title}>{t.intro}</PageHead>
      <section className="px-4 pb-20 pt-2">
        <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-[1.25fr_0.75fr]">
          <Reveal className="rounded-[2rem] bg-white p-6 shadow-card sm:p-8">
            {email ? (
              <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="text-sm font-medium">{t.form.name}<input className={`${field} mt-1.5`} value={f.name} onChange={set('name')} autoComplete="name" /></label>
                  <label className="text-sm font-medium">{t.form.email}<input className={`${field} mt-1.5`} type="email" value={f.email} onChange={set('email')} autoComplete="email" required /></label>
                </div>
                <label className="text-sm font-medium">{t.form.topic}
                  <select className={`${field} mt-1.5`} value={f.topic} onChange={(e) => setF({ ...f, topic: Number(e.target.value) })}>
                    {t.topics.map((x, i) => <option key={x} value={i}>{x}</option>)}
                  </select>
                </label>
                <label className="text-sm font-medium">{t.form.message}<textarea className={`${field} mt-1.5 min-h-[9rem] resize-y`} value={f.message} onChange={set('message')} required /></label>
                <button type="submit" className="btn-candy animate-shimmer inline-flex items-center justify-center gap-2 self-start rounded-full px-6 py-3 text-sm font-semibold text-white shadow-pop hover:-translate-y-0.5 hover:shadow-lift"><Send size={16} />{t.form.send}</button>
                {msg && <p role="status" className="rounded-2xl bg-violet-50 px-4 py-3 text-sm text-violet-700">{msg}</p>}
              </form>
            ) : (
              <div className="flex flex-col items-center gap-4 py-8 text-center">
                <img src="/recat-maintenance.webp" alt="" className="w-40 animate-floaty" width="160" height="147" loading="lazy" />
                <p className="max-w-sm text-ink-soft">{t.noEmail}</p>
              </div>
            )}
          </Reveal>

          <div className="flex flex-col gap-6">
            {channels.length > 0 && (
              <Reveal delay={100} className="rounded-[2rem] bg-white p-6 shadow-card">
                <h2 className="font-display text-lg font-semibold">{t.channels}</h2>
                <ul className="mt-4 flex flex-col gap-3">
                  {channels.map(({ icon: Icon, label, text, href }) => (
                    <li key={label} className="flex items-center gap-3">
                      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-violet-100 text-violet-600"><Icon size={18} /></span>
                      <div className="min-w-0 text-sm"><div className="text-xs text-ink-faint">{label}</div>
                        {href ? <a href={href} className="break-all font-medium hover:text-violet-700" {...(href.startsWith('http') ? { target: '_blank', rel: 'noopener noreferrer' } : {})}>{text}</a> : <span className="font-medium">{text}</span>}</div>
                    </li>
                  ))}
                </ul>
              </Reveal>
            )}
            <Reveal delay={200} className="rounded-[2rem] bg-gradient-to-br from-violet-50 to-pink-50 p-6 shadow-card">
              <h2 className="font-display text-lg font-semibold">{t.helpTitle}</h2>
              <p className="mt-2 text-sm text-ink-soft">{t.help}</p>
            </Reveal>
          </div>
        </div>
      </section>
    </>
  );
}
