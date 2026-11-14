import React, { useEffect, useState } from 'react';
import {
  LayoutDashboard, Users, Wallet, ListVideo, Mic, Settings as SettingsIcon, Menu, X, LogOut, ExternalLink, ScrollText, Megaphone,
} from 'lucide-react';
import { LangSwitch, useI18n } from './i18n.jsx';
import { btnGhost, useApi } from './ui.jsx';
import OverviewPage from './OverviewPage.jsx';
import UsersPage from './UsersPage.jsx';
import JobsPage from './JobsPage.jsx';
import TtsPage from './TtsPage.jsx';
import AuditPage from './AuditPage.jsx';
import SettingsPage from './SettingsPage.jsx';
import TopupsPage from './TopupsPage.jsx';
import PostsPage from './PostsPage.jsx';

// Admin dashboard shell: sidebar (desktop) / slide-in drawer (phone), header with language switch, and the page switch.
// Pages are one file each in this folder, shared pieces are in ui.jsx, Burmese texts in strings.js (used by i18n.jsx).
// Talks to /api/admin/* (backend/admin/); the API refuses anyone who is not is_admin.

const APP_URL = import.meta.env.VITE_APP_URL || ''; // optional link to the normal app

const NAV = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'users', label: 'Users', icon: Users },
  { id: 'topups', label: 'Top-ups', icon: Wallet },
  { id: 'jobs', label: 'Jobs', icon: ListVideo },
  { id: 'posts', label: 'Posts', icon: Megaphone },
  { id: 'tts', label: 'Voice models', icon: Mic },
  { id: 'audit', label: 'Audit log', icon: ScrollText },
  { id: 'settings', label: 'Settings', icon: SettingsIcon, superOnly: true },
];


export default function Admin({ account, onLogout }) {
  const { tr } = useI18n();
  const superadmin = !!account?.is_superadmin;   // the API enforces it; this only hides what the account cannot use
  const pages = NAV.filter((n) => !n.superOnly || superadmin);
  const [page, setPage] = useState(() => {
    const p = location.hash.slice(1);
    return pages.some((n) => n.id === p) ? p : 'overview';
  });
  const [drawer, setDrawer] = useState(false);
  const [userFilter, setUserFilter] = useState(null);
  const { data: ov, reload: reloadOv } = useApi('/api/admin/overview', { every: 30000 });
  const pending = ov?.topups_pending || 0;

  useEffect(() => { location.hash = page; }, [page]);
  const go = (id) => { if (!pages.some((n) => n.id === id)) return; setPage(id); setDrawer(false); if (id !== 'jobs') setUserFilter(null); window.scrollTo(0, 0); };
  const title = tr(NAV.find((n) => n.id === page)?.label || 'Admin');

  const nav = (
    <nav className="space-y-1.5">
      {pages.map(({ id, label, icon: Icon }) => (
        <button key={id} onClick={() => go(id)}
          className={`group flex w-full items-center gap-3 rounded-2xl px-3 py-2.5 text-sm font-medium ${page === id ? 'bg-gradient-to-r from-violet-500 to-violet-400 text-white shadow-pop' : 'text-ink-soft hover:bg-violet-50 hover:text-violet-600'}`}>
          <span className={`flex h-8 w-8 items-center justify-center rounded-xl transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-6 ${page === id ? 'bg-white/20' : 'bg-violet-50 text-violet-500'}`}><Icon size={16} /></span>{tr(label)}{id === 'topups' && pending > 0 && <span className="ml-auto rounded-full bg-amber-500 px-2 py-0.5 text-[11px] font-semibold text-ink">{pending}</span>}
        </button>
      ))}
    </nav>
  );
  const footer = (
    <div className="mt-auto space-y-2 text-xs text-ink-faint">
      <div className="truncate">{account?.email}</div>
      {APP_URL && <a href={APP_URL} className={`${btnGhost} w-full`}><ExternalLink size={15} />{tr('Open app')}</a>}
      <button onClick={onLogout} className={`${btnGhost} w-full`}><LogOut size={15} />{tr('Log out')}</button>
    </div>
  );

  return (
    <div className="min-h-screen font-sans text-ink md:flex md:h-screen md:overflow-hidden">
      <aside className="hidden h-full w-64 flex-shrink-0 flex-col border-r border-violet-100 bg-white/80 p-5 md:flex">
        <div className="mb-6"><span className="inline-flex items-center gap-2"><img src="/recat.webp" alt="" className="h-10 w-10 animate-floaty" /><span className="leading-tight"><span className="block text-lg font-bold tracking-tight whitespace-nowrap"><span className="bg-gradient-to-r from-violet-600 to-pink-500 bg-clip-text text-transparent">Recat</span> <span className="text-amber-500">Studio</span></span><span className="block text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint">{tr('Admin')}</span></span></span></div>
        {nav}{footer}
      </aside>

      {drawer && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setDrawer(false)}>
          <div className="absolute inset-0 bg-ink/40 backdrop-blur-sm" />
          <aside className="absolute left-0 top-0 flex h-full w-72 max-w-[85vw] flex-col rounded-r-[2rem] bg-white p-5 shadow-card" onClick={(e) => e.stopPropagation()}>
            <div className="mb-6 flex items-center justify-between"><span className="inline-flex items-center gap-2"><img src="/recat.webp" alt="" className="h-10 w-10 animate-floaty" /><span className="leading-tight"><span className="block text-lg font-bold tracking-tight whitespace-nowrap"><span className="bg-gradient-to-r from-violet-600 to-pink-500 bg-clip-text text-transparent">Recat</span> <span className="text-amber-500">Studio</span></span><span className="block text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint">{tr('Admin')}</span></span></span>
              <button onClick={() => setDrawer(false)} aria-label={tr('Close')} className="rounded-lg p-1 text-ink-soft"><X size={20} /></button></div>
            {nav}{footer}
          </aside>
        </div>
      )}

      <div className="min-w-0 flex-1 md:h-full md:overflow-y-auto">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-violet-100 bg-white/80 px-4 py-3 backdrop-blur">
          <button onClick={() => setDrawer(true)} aria-label={tr('Menu')} className="rounded-lg p-1.5 text-ink-soft hover:bg-violet-50 md:hidden"><Menu size={20} /></button>
          <h1 className="min-w-0 flex-1 truncate text-lg font-semibold">{title}</h1>
          <LangSwitch />
        </header>
        <main key={page} className="mx-auto max-w-6xl p-4 pb-16 md:p-6 animate-rise">
          {page === 'overview' && <OverviewPage go={go} />}
          {page === 'users' && <UsersPage me={account.id} superadmin={superadmin} openJobsFor={(u) => { setUserFilter(u); setPage('jobs'); }} />}
          {page === 'topups' && <TopupsPage onChanged={reloadOv} />}
          {page === 'jobs' && <JobsPage userFilter={userFilter} clearUser={() => setUserFilter(null)} />}
          {page === 'posts' && <PostsPage />}
          {page === 'tts' && <TtsPage />}
          {page === 'audit' && <AuditPage />}
          {page === 'settings' && superadmin && <SettingsPage />}
        </main>
      </div>
    </div>
  );
}
