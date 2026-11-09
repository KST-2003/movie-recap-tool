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
      const { data } = await axios.post('/api/auth/login', { email, password });
      if (!data.is_admin) { setError(tr('This account is not an admin.')); return; }
      onLogin(data.token);
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

  if (!token) return <><Login onLogin={login} />{problem && <p className="fixed inset-x-0 bottom-4 text-center text-sm text-red-400">{problem}</p>}</>;
  if (!account) return <div className="min-h-screen bg-slate-950 p-6 text-slate-400">{problem || '…'}</div>;
  return <Admin account={account} onLogout={logout} />;
}
