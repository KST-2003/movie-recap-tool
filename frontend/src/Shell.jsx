import React, { useEffect, useState } from 'react';
import { LangSwitch, useI18n } from './i18n.jsx';

// App frame: sidebar on wide screens, a top bar with a toggle (drawer) on phones.
const NAV = [
  ['create', '🎬', 'Create video'],
  ['usage', '📊', 'My usage'],
];

const mins = (seconds) => Math.max(0, seconds || 0) / 60;

function Meter({ label, used, limit }) {
  const { tr } = useI18n();
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 100;
  const full = limit > 0 && used >= limit;
  const warn = pct >= 80;
  return (
    <div>
      <div className="flex justify-between text-[11px] text-slate-400 mb-1">
        <span>{label}</span>
        <span className="text-slate-300">{tr('{used} / {limit} min', { used: Math.round(used), limit })}</span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
        <div className={`h-full rounded-full ${full ? 'bg-red-500' : warn ? 'bg-amber-400' : 'bg-purple-400'}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function SidebarBody({ view, setView, account, onLogout, close }) {
  const { tr } = useI18n();
  return (
    <div className="h-full flex flex-col gap-5 p-4">
      <div className="text-lg font-bold text-purple-400 flex items-center gap-2">🎬 <span>Movie Recap Tool</span></div>
      <nav className="flex flex-col gap-1">
        {NAV.map(([key, icon, label]) => (
          <button
            key={key} type="button" onClick={() => { setView(key); close?.(); }}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-left ${view === key ? 'bg-purple-600/30 text-white border border-purple-500/50' : 'text-slate-300 hover:bg-slate-800 border border-transparent'}`}
          >
            <span>{icon}</span>{tr(label)}
          </button>
        ))}
      </nav>
      {account && (
        <div className="space-y-3 rounded-xl border border-slate-800 bg-slate-950/40 p-3">
          <Meter label={tr('Today')} used={mins(account.used_seconds)} limit={account.daily_minutes} />
          <Meter label={tr('This month')} used={mins(account.month_used_seconds)} limit={account.monthly_minutes} />
        </div>
      )}
      <div className="mt-auto space-y-3">
        {account && <p className="text-xs text-slate-400 break-all">{account.email}</p>}
        <div className="flex items-center justify-between">
          <LangSwitch />
          <button type="button" onClick={onLogout} className="text-xs text-slate-400 hover:text-white">{tr('Log out')}</button>
        </div>
      </div>
    </div>
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

  return (
    <div className="min-h-screen bg-slate-950 text-white font-sans lg:flex">
      {/* Wide screens: fixed sidebar */}
      <aside className="hidden lg:block w-64 shrink-0 border-r border-slate-800 bg-slate-900 sticky top-0 h-screen overflow-y-auto">
        <SidebarBody view={view} setView={setView} account={account} onLogout={onLogout} />
      </aside>

      {/* Phones: top bar with a toggle button + drawer */}
      <header className="lg:hidden sticky top-0 z-30 flex items-center gap-3 px-4 py-3 bg-slate-900/95 backdrop-blur border-b border-slate-800">
        <button type="button" aria-label={tr('Menu')} aria-expanded={open} onClick={() => setOpen(true)}
          className="w-10 h-10 rounded-xl bg-slate-800 hover:bg-slate-700 flex flex-col items-center justify-center gap-1">
          <span className="block w-5 h-0.5 bg-slate-200" /><span className="block w-5 h-0.5 bg-slate-200" /><span className="block w-5 h-0.5 bg-slate-200" />
        </button>
        <span className="font-bold text-purple-400 truncate">🎬 Movie Recap Tool</span>
        {left != null && <span className="ml-auto text-xs text-slate-400 whitespace-nowrap">{tr('{n} min left', { n: left })}</span>}
      </header>
      {open && (
        <div className="lg:hidden fixed inset-0 z-40">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-0 bottom-0 w-72 max-w-[85vw] bg-slate-900 border-r border-slate-800 shadow-2xl overflow-y-auto">
            <button type="button" aria-label={tr('Close menu')} onClick={() => setOpen(false)} className="absolute right-3 top-3 w-8 h-8 rounded-full bg-slate-800 text-slate-300">✕</button>
            <SidebarBody view={view} setView={setView} account={account} onLogout={onLogout} close={() => setOpen(false)} />
          </div>
        </div>
      )}

      <main className="flex-1 min-w-0 p-4 sm:p-6">{children}</main>
    </div>
  );
}
