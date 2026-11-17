import React from 'react';
import { Link } from 'react-router-dom';

// A puffy popcorn kernel drawn with SVG (no image needed).
export function Kernel({ className = '', style, size = 34 }) {
  return (
    <svg className={className} style={style} width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
      <g fill="#FFE8A3" stroke="#F5B942" strokeWidth="1.6">
        <circle cx="14" cy="22" r="9" /><circle cx="26" cy="22" r="9" /><circle cx="20" cy="13" r="9" /><circle cx="20" cy="25" r="8" />
      </g>
      <g fill="#FFF6D6"><circle cx="16" cy="12" r="2.6" /><circle cx="27" cy="20" r="2.2" /><circle cx="12" cy="22" r="2" /></g>
    </svg>
  );
}

export function Heart({ className = '', style, size = 22 }) {
  return (
    <svg className={className} style={style} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 21s-7.5-4.6-9.5-9.2C1.2 8.4 3 5 6.4 5c2 0 3.7 1.1 4.6 2.7h2C14 6.1 15.6 5 17.6 5 21 5 22.8 8.4 21.5 11.8 19.5 16.4 12 21 12 21z" fill="#F472B6" />
    </svg>
  );
}

export function Sparkle({ className = '', style, size = 18, color = '#FFD976' }) {
  return (
    <svg className={className} style={style} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 0c.8 6.4 5.6 11.2 12 12-6.4.8-11.2 5.6-12 12-.8-6.4-5.6-11.2-12-12 6.4-.8 11.2-5.6 12-12z" fill={color} />
    </svg>
  );
}

// Soft coloured blobs that drift behind a section.
export function Blobs() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      <div className="absolute -left-24 -top-24 h-[28rem] w-[28rem] rounded-full bg-lavender/50 blur-3xl animate-drift" />
      <div className="absolute -right-20 top-10 h-[24rem] w-[24rem] rounded-full bg-blush/50 blur-3xl animate-drift [animation-delay:-4s]" />
      <div className="absolute bottom-[-8rem] left-1/3 h-[22rem] w-[22rem] rounded-full bg-popcorn/30 blur-3xl animate-drift [animation-delay:-8s]" />
    </div>
  );
}

// The page's top decoration for inner pages.
export function PageHead({ kicker, title, children }) {
  return (
    <section className="relative overflow-hidden px-4 pb-10 pt-32 sm:pt-36">
      <Blobs />
      <div className="relative mx-auto max-w-3xl text-center">
        <span className="page-in inline-block rounded-full bg-white/80 px-4 py-1.5 text-xs font-semibold uppercase tracking-wider text-violet-600 shadow-card">{kicker}</span>
        <h1 className="page-in mt-4 font-display text-4xl font-semibold leading-tight sm:text-5xl [animation-delay:80ms]">{title}</h1>
        {children && <p className="page-in mx-auto mt-4 max-w-2xl text-base text-ink-soft sm:text-lg [animation-delay:160ms]">{children}</p>}
      </div>
    </section>
  );
}

// One button for everything: `to` = a page of this site, `href` = another address (opens in a new tab when `external`).
export function Btn({ to, href, external, variant = 'primary', className = '', children, ...rest }) {
  const base = 'inline-flex items-center justify-center gap-2 rounded-full px-6 py-3 text-sm font-semibold hover:-translate-y-0.5';
  const look = variant === 'primary'
    ? 'btn-candy animate-shimmer text-white shadow-pop hover:shadow-lift'
    : 'border border-violet-200 bg-white/80 text-violet-700 shadow-card hover:bg-white hover:shadow-lift';
  const cls = `${base} ${look} ${className}`;
  if (to) return <Link to={to} className={cls} {...rest}>{children}</Link>;
  return <a href={href} className={cls} {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})} {...rest}>{children}</a>;
}
