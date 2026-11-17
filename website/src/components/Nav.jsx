import React, { useEffect, useState } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { Menu, X, ArrowRight } from 'lucide-react';
import { useLang } from '../lang.jsx';
import { SITE } from '../site.config.js';
import { Btn } from './Bits.jsx';

export function Brand({ small }) {
  return (
    <Link to="/" className="flex items-center gap-2.5 font-display text-lg font-semibold" aria-label="Recat Studio">
      <img src="/recat-icon.png" alt="" width="36" height="36" className={`${small ? 'h-8 w-8' : 'h-9 w-9'} rounded-xl transition-transform duration-300 hover:rotate-12`} />
      <span>Recat <span className="text-amber-500">Studio</span></span>
    </Link>
  );
}

function LangSwitch() {
  const { lang, setLang } = useLang();
  return (
    <div className="flex rounded-full bg-violet-100/80 p-0.5 text-xs font-semibold" role="group" aria-label="Language">
      {[['en', 'EN'], ['my', 'မြန်မာ']].map(([k, l]) => (
        <button key={k} onClick={() => setLang(k)} aria-pressed={lang === k} className={`rounded-full px-3 py-1.5 ${lang === k ? 'bg-white text-violet-700 shadow-card' : 'text-ink-soft hover:text-violet-700'}`}>{l}</button>
      ))}
    </div>
  );
}

export default function Nav() {
  const { c } = useLang();
  const [open, setOpen] = useState(false);
  const [solid, setSolid] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname, loc.hash]);
  useEffect(() => {
    const on = () => setSolid(window.scrollY > 12);
    on();
    window.addEventListener('scroll', on, { passive: true });
    return () => window.removeEventListener('scroll', on);
  }, []);
  useEffect(() => { document.body.style.overflow = open ? 'hidden' : ''; return () => { document.body.style.overflow = ''; }; }, [open]);

  const links = [['/', c.nav.home], ['/#features', c.nav.features], ['/#how', c.nav.how], ['/pricing', c.nav.pricing], ['/about', c.nav.about], ['/contact', c.nav.contact]];
  const cls = ({ isActive }) => `rounded-full px-3 py-2 text-sm font-medium ${isActive ? 'bg-violet-100 text-violet-700' : 'text-ink-soft hover:bg-violet-50 hover:text-violet-700'}`;

  return (
    <header className={`fixed inset-x-0 top-0 z-50 transition-all duration-300 ${solid || open ? 'glass shadow-card' : ''}`}>
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
        <Brand />
        <nav className="hidden items-center gap-1 lg:flex" aria-label="Main">
          {links.map(([to, label]) => (to.includes('#')
            ? <Link key={to} to={to} className="rounded-full px-3 py-2 text-sm font-medium text-ink-soft hover:bg-violet-50 hover:text-violet-700">{label}</Link>
            : <NavLink key={to} to={to} end={to === '/'} className={cls}>{label}</NavLink>))}
        </nav>
        <div className="flex items-center gap-2">
          <div className="hidden sm:block"><LangSwitch /></div>
          <Btn href={SITE.appUrl} external className="hidden !px-5 !py-2.5 sm:inline-flex">{c.nav.login}<ArrowRight size={16} /></Btn>
          <button className="rounded-full bg-white/90 p-2.5 text-violet-700 shadow-card lg:hidden" onClick={() => setOpen(!open)} aria-label={c.nav.menu} aria-expanded={open}>{open ? <X size={20} /> : <Menu size={20} />}</button>
        </div>
      </div>
      {open && (
        <div className="glass page-in border-t border-violet-100 px-4 pb-6 pt-2 lg:hidden" style={{ height: 'calc(100vh - 62px)' }}>
          <nav className="flex flex-col gap-1" aria-label="Mobile">
            {links.map(([to, label], i) => (
              <Link key={to} to={to} className="page-in rounded-2xl px-4 py-3.5 text-lg font-medium text-ink hover:bg-violet-50" style={{ animationDelay: `${i * 40}ms` }}>{label}</Link>
            ))}
          </nav>
          <div className="mt-4 flex flex-col gap-3 px-1">
            <LangSwitch />
            <Btn href={SITE.appUrl} external>{c.nav.open}<ArrowRight size={16} /></Btn>
          </div>
        </div>
      )}
    </header>
  );
}
