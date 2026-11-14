import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { LangSwitch, useI18n } from './i18n.jsx';
import Admin from './Admin.jsx';

// Sign-in gate of the admin app. It has its own login (the normal app lives on another origin, so its session is not shared);
// the token is kept per browser under its own key. The server is what really enforces is_admin; this screen only avoids
// showing a dashboard full of 403 errors to a normal account.
const TOKEN_KEY = 'admin_token';
const readToken = () => { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; } };
const saveToken = (t) => { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch (e) { /* ignore */ } };
const errText = (e) => e?.response?.data?.detail || '';
const deviceId = () => {
  try {
    let id = localStorage.getItem('admin_device_id');
    if (!id) { id = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}${Math.random().toString(36).slice(2)}`).replace(/[^A-Za-z0-9_-]/g, ''); localStorage.setItem('admin_device_id', id); }
    return id;
  } catch (e) { return 'unknown'; }
};

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
      const { data } = await axios.post('/api/auth/login', { email: email.trim(), password, device_id: deviceId() });
      if (!data.is_admin) { setError(tr('This account is not an admin.')); return; }
      onLogin(data.token);
    } catch (err) {
      setError(errText(err) ? trs(errText(err)) : tr('Could not reach the server.'));
    } finally { setBusy(false); }
  };

  const input = 'w-full rounded-2xl bg-page border border-violet-100 px-4 py-3 text-sm text-ink placeholder:text-ink-faint outline-none transition-shadow focus:border-violet-400 focus:shadow-[0_0_0_4px_rgba(139,92,246,0.15)]';
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-6 font-sans text-ink">
      <div aria-hidden="true" className="pointer-events-none absolute -top-24 -left-20 h-72 w-72 rounded-full bg-lavender/50 blur-3xl animate-drift" />
      <div aria-hidden="true" className="pointer-events-none absolute -bottom-24 -right-16 h-80 w-80 rounded-full bg-blush/50 blur-3xl animate-drift [animation-delay:-4s]" />
      <div className="absolute right-4 top-4"><LangSwitch /></div>
      <form onSubmit={submit} className="relative w-full max-w-sm space-y-4 rounded-[2rem] border border-white bg-white/90 p-7 pt-16 shadow-card animate-rise">
        <div className="absolute -top-14 left-1/2 -translate-x-1/2 rounded-full bg-white p-2 shadow-card"><img src="/recat.webp" alt="" className="h-24 w-24 animate-floaty" /></div>
        <div className="text-center">
          <h1 className="text-3xl font-bold tracking-tight whitespace-nowrap"><span className="bg-gradient-to-r from-violet-600 to-pink-500 bg-clip-text text-transparent">Recat</span> <span className="text-amber-500">Studio</span></h1>
          <p className="mt-1 text-sm text-ink-soft">{tr('Admin sign in')}</p>
        </div>
        <input className={input} type="text" autoCapitalize="none" autoComplete="username" placeholder={tr('Username')} value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input className={input} type="password" autoComplete="current-password" placeholder={tr('Password')} value={password} onChange={(e) => setPassword(e.target.value)} required />
        {error && <p className="rounded-2xl bg-rose-50 px-3 py-2 text-sm text-rose-600 animate-pop">{error}</p>}
        <button disabled={busy} className="btn-candy animate-shimmer w-full rounded-2xl py-3 font-semibold text-white shadow-pop hover:-translate-y-0.5 disabled:opacity-50">{busy ? tr('Signing in…') : tr('Log in')}</button>
      </form>
    </div>
  );
}

export default function App() {
  const { tr } = useI18n();
  const [token, setToken] = useState(readToken);
  const [account, setAccount] = useState(null);
  const [problem, setProblem] = useState('');
  if (token) axios.defaults.headers.common.Authorization = `Bearer ${token}`;

  const logout = () => {
    saveToken('');
    delete axios.defaults.headers.common.Authorization;
    setToken(''); setAccount(null);
  };
  const login = (t) => { saveToken(t); axios.defaults.headers.common.Authorization = `Bearer ${t}`; setProblem(''); setToken(t); };

  useEffect(() => {
    const id = axios.interceptors.response.use((r) => r, (err) => {
      if (err.response?.status === 401 && !String(err.config?.url).includes('/api/auth/')) logout();
      return Promise.reject(err);
    });
    return () => axios.interceptors.response.eject(id);
  }, []);

  // who am I? (also catches a stored token of an account that lost admin rights)
  useEffect(() => {
    if (!token) return;
    axios.get('/api/auth/me').then((r) => {
      if (r.data.is_admin) setAccount(r.data); else { logout(); setProblem(tr('This account is not an admin.')); }
    }).catch((e) => { if (e.response?.status !== 401) setProblem(tr('Could not reach the server.')); });
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!token) return <><Login onLogin={login} />{problem && <p className="fixed inset-x-0 bottom-4 text-center text-sm text-rose-500">{problem}</p>}</>;
  if (!account) return <div className="min-h-screen p-6 text-ink-soft">{problem || '…'}</div>;
  return <Admin account={account} onLogout={logout} />;
}
