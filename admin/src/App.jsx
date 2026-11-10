import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { LangSwitch, useI18n } from './i18n.jsx';
import Admin from './Admin.jsx';

// Sign-in gate of the admin app. The session is an httpOnly cookie set by the API: JavaScript cannot read it, so a script injected into this page
// cannot steal it (the old token in localStorage could be stolen). All this file keeps is the CSRF token, in memory only. The server enforces is_admin
// AND that admin sessions are only used from this dashboard's origin (ADMIN_ORIGINS), so a script in the normal app cannot ride an admin's cookie.
const errText = (e) => e?.response?.data?.detail || '';

axios.defaults.withCredentials = true;                    // send the session cookie to the API
axios.defaults.headers.common['X-Audience'] = 'admin';    // "this is the admin dashboard": the API reads the admin cookie
let csrfToken = '';
axios.interceptors.request.use((config) => {              // anything that changes data must carry the CSRF token
  if (csrfToken && !/^(get|head|options)$/i.test(config.method || 'get')) config.headers['X-CSRF-Token'] = csrfToken;
  return config;
});

function Login({ onLogin }) {
  const { tr, trs } = useI18n();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError('');
    try {
      const { data } = await axios.post('/api/auth/login', { email, password, audience: 'admin', cookie: true });
      onLogin(data);
    } catch (err) {
      setError(errText(err) ? trs(errText(err)) : tr('Could not reach the server.'));
    } finally { setBusy(false); }
  };

  const input = 'w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white outline-none focus:border-purple-500';
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 p-6 font-sans text-white">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl">
        <div className="flex items-center justify-between gap-2"><h1 className="text-xl font-bold text-purple-400">🎬 {tr('Admin sign in')}</h1><LangSwitch /></div>
        <input className={input} type="email" autoComplete="username" placeholder={tr('Email')} value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input className={input} type="password" autoComplete="current-password" placeholder={tr('Password')} value={password} onChange={(e) => setPassword(e.target.value)} required />
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button disabled={busy} className="w-full rounded-xl bg-purple-600 py-2 font-semibold hover:bg-purple-500 disabled:opacity-50">{busy ? tr('Signing in…') : tr('Log in')}</button>
      </form>
    </div>
  );
}

export default function App() {
  const { tr } = useI18n();
  const [signedIn, setSignedIn] = useState(null);   // null = still asking the server, false = sign-in screen, true = in
  const [account, setAccount] = useState(null);
  const [problem, setProblem] = useState('');

  // The server deletes the cookie (JavaScript cannot touch an httpOnly cookie).
  const logout = (callServer = true) => {
    csrfToken = '';
    setSignedIn(false); setAccount(null);
    if (callServer) axios.post('/api/auth/logout').catch(() => {});
  };

  // Who am I? Also what a page reload does: the cookie survives, the CSRF token in memory does not, /me hands it out again.
  const loadMe = () => axios.get('/api/auth/me').then((r) => {
    csrfToken = r.data.csrf_token || csrfToken;
    if (r.data.is_admin) { setAccount(r.data); setSignedIn(true); } else { logout(); setProblem(tr('This account is not an admin.')); }
  }).catch((e) => {
    setSignedIn(false);
    if (e.response?.status !== 401) setProblem(tr('Could not reach the server.'));
  });
  const login = (data) => { csrfToken = data.csrf_token || ''; setProblem(''); setSignedIn(true); loadMe(); };

  useEffect(() => {
    try { localStorage.removeItem('admin_token'); } catch (e) { /* the old place of the token: nothing may stay there */ }
    loadMe();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const id = axios.interceptors.response.use((r) => r, (err) => {
      if (err.response?.status === 401 && !String(err.config?.url).includes('/api/auth/')) logout(false);
      return Promise.reject(err);
    });
    return () => axios.interceptors.response.eject(id);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Admin sessions last 60 minutes: renew every 10 minutes (and when the tab comes back) while the dashboard is open. A 401 means the session
  // was cancelled (password reset, demotion, "log out everywhere") or is older than the 12-hour maximum: back to the sign-in screen.
  useEffect(() => {
    if (!signedIn) return undefined;
    let stopped = false;
    const renew = () => axios.post('/api/auth/refresh').then((r) => {
      if (!stopped) csrfToken = r.data.csrf_token || csrfToken;
    }).catch((err) => { if (err.response?.status === 401) logout(false); });
    const timer = setInterval(renew, 10 * 60 * 1000);
    const onVisible = () => { if (document.visibilityState === 'visible') renew(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => { stopped = true; clearInterval(timer); document.removeEventListener('visibilitychange', onVisible); };
  }, [signedIn]); // eslint-disable-line react-hooks/exhaustive-deps

  if (signedIn === null) return <div className="min-h-screen bg-slate-950 p-6 text-slate-400">…</div>;
  if (!signedIn) return <><Login onLogin={login} />{problem && <p className="fixed inset-x-0 bottom-4 text-center text-sm text-red-400">{problem}</p>}</>;
  if (!account) return <div className="min-h-screen bg-slate-950 p-6 text-slate-400">{problem || '…'}</div>;
  return <Admin account={account} onLogout={logout} />;
}
