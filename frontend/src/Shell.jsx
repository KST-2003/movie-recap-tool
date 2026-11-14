import React, { useEffect, useState } from 'react';
import { LangSwitch, useI18n } from './i18n.jsx';
import Mascot, { Brand } from './Mascot.jsx';

// App frame (Recat look): white sidebar on wide screens; on phones a small top bar + a bottom tab bar, the account sheet
// (allowance meters, language, log out) opens from the round button at the top right.
const ICONS = {
  create: <path d="M12 5v14M5 12h14" />,
  history: <><rect x="3" y="5" width="18" height="14" rx="3" /><path d="M10 9.5v5l4.5-2.5z" /></>,
  topup: <><rect x="3" y="6" width="18" height="13" rx="3" /><path d="M3 10.5h18M7 15h3" /></>,
  usage: <path d="M5 19V11M12 19V5M19 19v-6" />,
};
const NAV = [
  ['create', 'Create video', 'Create'],
  ['history', 'My videos', 'Videos'],
  ['topup', 'Top up', 'Top up'],
  ['usage', 'My usage', 'Usage'],
];
function Icon({ name, className = 'h-5 w-5' }) {
  return <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICONS[name]}</svg>;
}

const mins = (seconds) => Math.max(0, seconds || 0) / 60;

function Meter({ label, used, limit }) {
  const { tr } = useI18n();
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 100;
  const full = limit > 0 && used >= limit;
  const warn = pct >= 80;
  return (
    <div>
      <div className="flex justify-between text-[11px] text-ink-soft mb-1">
        <span>{label}</span>
        <span className="text-ink font-medium">{tr('{used} / {limit} min', { used: Math.round(used), limit })}</span>
      </div>
      <div className="h-2 rounded-full bg-violet-100 overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-700 ease-out ${full ? 'bg-rose-400' : warn ? 'bg-popcorn' : 'bg-gradient-to-r from-violet-400 to-pink-300'}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function AccountBox({ account, onLogout }) {
  const { tr } = useI18n();
  return (
    <>
      {account && (
        <div className="space-y-3 rounded-2xl bg-page border border-violet-100 p-3">
          <Meter label={tr('Today')} used={mins(account.used_seconds)} limit={account.daily_minutes} />
          <Meter label={tr('This month')} used={mins(account.month_used_seconds)} limit={account.monthly_minutes} />
          <div className="flex justify-between text-[11px] text-ink-soft"><span>{tr('Bought minutes')}</span><span className="text-ink font-medium">{Math.floor(mins(account.credit_seconds))} {tr('min')}</span></div>
        </div>
      )}
      <div className="mt-auto space-y-3">
        {account && <p className="text-xs text-ink-soft break-all">{account.email}</p>}
        <div className="flex items-center justify-between">
          <LangSwitch />
          <button type="button" onClick={onLogout} className="text-xs font-medium text-ink-soft hover:text-violet-600">{tr('Log out')}</button>
        </div>
      </div>
    </>
  );
}

export default function Shell({ view, setView, account, onLogout, children }) {
  const { tr } = useI18n();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === 'Escape' && setOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);
  const left = account ? Math.floor(account.remaining_seconds / 60) : null;
  const initial = (account?.email || '?').slice(0, 1).toUpperCase();

  return (
    <div className="min-h-screen text-ink font-sans lg:flex lg:h-screen lg:overflow-hidden">
      {/* Wide screens: sidebar */}
      <aside className="hidden lg:flex flex-col gap-6 w-64 shrink-0 h-full p-5 bg-white/80 backdrop-blur border-r border-violet-100 overflow-y-auto">
        <Brand />
        <nav className="flex flex-col gap-1.5">
          {NAV.map(([key, label]) => (
            <button key={key} type="button" onClick={() => setView(key)} aria-current={view === key ? 'page' : undefined}
              className={`group flex items-center gap-3 px-3 py-2.5 rounded-2xl text-sm font-medium text-left ${view === key
                ? 'bg-gradient-to-r from-violet-500 to-violet-400 text-white shadow-pop'
                : 'text-ink-soft hover:bg-violet-50 hover:text-violet-600'}`}>
              <span className={`flex h-8 w-8 items-center justify-center rounded-xl transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-6 ${view === key ? 'bg-white/20' : 'bg-violet-50 text-violet-500'}`}><Icon name={key} className="h-4 w-4" /></span>
              {tr(label)}
            </button>
          ))}
        </nav>
        <AccountBox account={account} onLogout={onLogout} />
      </aside>

      {/* Phones: top bar */}
      <header className="lg:hidden sticky top-0 z-30 flex items-center gap-3 px-4 py-2.5 bg-white/80 backdrop-blur border-b border-violet-100">
        <Brand size="text-lg" icon="h-9 w-9" />
        {left != null && <span className="ml-auto min-w-0 truncate rounded-full bg-violet-50 px-3 py-1 text-xs font-medium text-violet-600">{tr('{n} min left', { n: left })}</span>}
        <button type="button" aria-label={tr('Menu')} aria-expanded={open} onClick={() => setOpen(true)}
          className={`${left == null ? 'ml-auto' : ''} h-9 w-9 shrink-0 rounded-full bg-gradient-to-br from-violet-400 to-pink-300 text-sm font-bold text-white shadow-pop`}>{initial}</button>
      </header>
      {open && (
        <div className="lg:hidden fixed inset-0 z-50">
          <div className="absolute inset-0 bg-ink/40 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <div className="absolute inset-x-0 bottom-0 max-h-[85vh] overflow-y-auto rounded-t-[2rem] bg-white p-5 pb-8 shadow-2xl animate-rise flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <Brand size="text-lg" icon="h-9 w-9" />
              <button type="button" aria-label={tr('Close menu')} onClick={() => setOpen(false)} className="h-8 w-8 rounded-full bg-violet-50 text-ink-soft">✕</button>
            </div>
            <AccountBox account={account} onLogout={onLogout} />
          </div>
        </div>
      )}

      <main className="flex-1 min-w-0 p-4 pb-28 sm:p-6 sm:pb-28 lg:pb-6 lg:h-full lg:overflow-y-auto">{children}</main>

      {/* Phones: bottom tab bar */}
      <nav className="lg:hidden fixed inset-x-0 bottom-0 z-30 flex items-stretch justify-around gap-1 rounded-t-[1.75rem] border-t border-violet-100 bg-white/95 px-3 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] shadow-[0_-10px_30px_-12px_rgba(139,92,246,0.3)] backdrop-blur">
        {NAV.map(([key, label, short]) => (
          <button key={key} type="button" onClick={() => setView(key)} aria-label={tr(label)} aria-current={view === key ? 'page' : undefined}
            className={`flex min-w-0 flex-1 flex-col items-center gap-0.5 rounded-2xl py-1.5 text-[11px] font-medium ${view === key ? 'bg-violet-100 text-violet-600' : 'text-ink-faint'}`}>
            <Icon name={key} className={`h-5 w-5 transition-transform duration-300 ${view === key ? 'scale-110 -translate-y-0.5' : ''}`} />
            <span className="max-w-full truncate">{tr(short)}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
