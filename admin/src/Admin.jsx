import React, { lazy, Suspense, useEffect, useState } from 'react';
import {
  LayoutDashboard, Users, ListVideo, Mic, Settings as SettingsIcon, Menu, X, LogOut, ExternalLink, ScrollText,
} from 'lucide-react';
import { LangSwitch, useI18n } from './i18n.jsx';
import { btnGhost } from './ui.jsx';

// Admin dashboard shell: sidebar (desktop) / slide-in drawer (phone), header with language switch, and the page switch.
// Pages are one file each in this folder, shared pieces are in ui.jsx, Burmese texts in strings.js (used by i18n.jsx).
// Talks to /api/admin/* (backend/admin/); the API refuses anyone who is not is_admin.
// Code-split: only ONE page is ever shown at a time, so there's no reason to make every admin download all six on login.
const OverviewPage = lazy(() => import('./OverviewPage.jsx'));
const UsersPage = lazy(() => import('./UsersPage.jsx'));
const JobsPage = lazy(() => import('./JobsPage.jsx'));
const TtsPage = lazy(() => import('./TtsPage.jsx'));
const AuditPage = lazy(() => import('./AuditPage.jsx'));
const SettingsPage = lazy(() => import('./SettingsPage.jsx'));

const APP_URL = import.meta.env.VITE_APP_URL || ''; // optional link to the normal app

const NAV = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'users', label: 'Users', icon: Users },
  { id: 'jobs', label: 'Jobs', icon: ListVideo },
  { id: 'tts', label: 'Voice models', icon: Mic },
  { id: 'audit', label: 'Audit log', icon: ScrollText },
  { id: 'settings', label: 'Settings', icon: SettingsIcon },
];


export default function Admin({ account, onLogout }) {
  const { tr } = useI18n();
  const [page, setPage] = useState(() => {
    const p = location.hash.slice(1);
    return NAV.some((n) => n.id === p) ? p : 'overview';
  });
  const [drawer, setDrawer] = useState(false);
  const [userFilter, setUserFilter] = useState(null);

  useEffect(() => { location.hash = page; }, [page]);
  const go = (id) => { setPage(id); setDrawer(false); if (id !== 'jobs') setUserFilter(null); window.scrollTo(0, 0); };
  const title = tr(NAV.find((n) => n.id === page)?.label || 'Admin');

  const nav = (
    <nav className="space-y-1">
      {NAV.map(({ id, label, icon: Icon }) => (
        <button key={id} onClick={() => go(id)}
          className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm ${page === id ? 'bg-purple-600/20 text-purple-200' : 'text-slate-300 hover:bg-slate-800'}`}>
          <Icon size={18} />{tr(label)}
        </button>
      ))}
    </nav>
  );
  const footer = (
    <div className="mt-auto space-y-2 text-xs text-slate-500">
      <div className="truncate">{account?.email}</div>
      {APP_URL && <a href={APP_URL} className={`${btnGhost} w-full`}><ExternalLink size={15} />{tr('Open app')}</a>}
      <button onClick={onLogout} className={`${btnGhost} w-full`}><LogOut size={15} />{tr('Log out')}</button>
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-950 font-sans text-white md:flex md:h-screen md:overflow-hidden">
      <aside className="hidden h-full w-60 flex-shrink-0 flex-col border-r border-slate-800 bg-slate-900 p-4 md:flex">
        <div className="mb-6 text-lg font-bold text-purple-400">🎬 {tr('Admin')}</div>
        {nav}{footer}
      </aside>

      {drawer && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setDrawer(false)}>
          <div className="absolute inset-0 bg-black/60" />
          <aside className="absolute left-0 top-0 flex h-full w-72 max-w-[85vw] flex-col border-r border-slate-800 bg-slate-900 p-4" onClick={(e) => e.stopPropagation()}>
            <div className="mb-6 flex items-center justify-between"><span className="text-lg font-bold text-purple-400">🎬 {tr('Admin')}</span>
              <button onClick={() => setDrawer(false)} aria-label={tr('Close')} className="rounded-lg p-1 text-slate-400"><X size={20} /></button></div>
            {nav}{footer}
          </aside>
        </div>
      )}

      <div className="min-w-0 flex-1 md:h-full md:overflow-y-auto">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-slate-800 bg-slate-950/90 px-4 py-3 backdrop-blur">
          <button onClick={() => setDrawer(true)} aria-label={tr('Menu')} className="rounded-lg p-1.5 text-slate-300 hover:bg-slate-800 md:hidden"><Menu size={20} /></button>
          <h1 className="min-w-0 flex-1 truncate text-lg font-semibold">{title}</h1>
          <LangSwitch />
        </header>
        <main className="mx-auto max-w-6xl p-4 pb-16 md:p-6">
          <Suspense fallback={<p className="text-sm text-slate-400">{tr('Loading…')}</p>}>
            {page === 'overview' && <OverviewPage go={go} />}
            {page === 'users' && <UsersPage me={account.id} openJobsFor={(u) => { setUserFilter(u); setPage('jobs'); }} />}
            {page === 'jobs' && <JobsPage userFilter={userFilter} clearUser={() => setUserFilter(null)} />}
            {page === 'tts' && <TtsPage />}
            {page === 'audit' && <AuditPage />}
            {page === 'settings' && <SettingsPage />}
          </Suspense>
        </main>
      </div>
    </div>
  );
}
