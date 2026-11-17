import React from 'react';
import { Link } from 'react-router-dom';
import { useLang } from '../lang.jsx';
import { SITE } from '../site.config.js';
import { Brand } from './Nav.jsx';
import { Kernel } from './Bits.jsx';

export default function Footer() {
  const { c } = useLang();
  const f = c.footer;
  const col = 'text-sm text-ink-soft hover:text-violet-700';
  return (
    <footer className="relative mt-10 overflow-hidden border-t border-violet-100 bg-white/70">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-12 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <div>
          <Brand />
          <p className="mt-3 max-w-xs text-sm text-ink-soft">{f.tag}</p>
          <a href={SITE.appUrl} className="mt-4 inline-block text-sm font-semibold text-violet-700 hover:underline">{c.nav.open} →</a>
        </div>
        <div className="flex flex-col gap-2.5"><div className="text-xs font-semibold uppercase tracking-wider text-ink-faint">{f.product}</div>
          <Link className={col} to="/#features">{c.nav.features}</Link><Link className={col} to="/#how">{c.nav.how}</Link><Link className={col} to="/pricing">{c.nav.pricing}</Link></div>
        <div className="flex flex-col gap-2.5"><div className="text-xs font-semibold uppercase tracking-wider text-ink-faint">{f.company}</div>
          <Link className={col} to="/about">{c.nav.about}</Link><Link className={col} to="/contact">{c.nav.contact}</Link></div>
        <div className="flex flex-col gap-2.5"><div className="text-xs font-semibold uppercase tracking-wider text-ink-faint">{f.legal}</div>
          <Link className={col} to="/privacy">{f.privacy}</Link><Link className={col} to="/terms">{f.terms}</Link></div>
      </div>
      <div className="border-t border-violet-100">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-5 text-xs text-ink-faint">
          <span>© {new Date().getFullYear()} {SITE.name}. {f.rights}</span>
          <span className="inline-flex items-center gap-1.5">{f.madeWith}<Kernel size={18} className="animate-kernel" /></span>
        </div>
      </div>
    </footer>
  );
}
