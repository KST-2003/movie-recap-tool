import React, { useState } from 'react';
import { LangSwitch, useI18n } from './i18n.jsx';
import * as authApi from './api/auth.js';

export default function AuthScreen({ onAuth }) {
  const { tr, trs } = useI18n();
  const [mode, setMode] = useState('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const { data } = await (mode === 'login' ? authApi.login : authApi.register)(email, password);
      onAuth(data);
    } catch (err) {
      setError(trs(err.response?.data?.detail) || tr('Could not reach the server.'));
    } finally {
      setBusy(false);
    }
  };

  const input = 'w-full rounded-xl bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-white outline-none focus:border-purple-500';
  return (
    <div className="min-h-screen bg-slate-950 text-white p-6 font-sans flex items-center justify-center">
      <form onSubmit={submit} className="w-full max-w-sm bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-4">
        <div className="flex items-center justify-between"><h1 className="text-xl font-bold text-purple-400">🎬 Movie Recap Tool</h1><LangSwitch /></div>
        <input className={input} type="email" placeholder={tr('Email')} value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input className={input} type="password" placeholder={tr('Password (8+ characters)')} value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button disabled={busy} className="w-full py-2 rounded-xl bg-purple-600 hover:bg-purple-500 font-semibold disabled:opacity-50">
          {mode === 'login' ? tr('Log in') : tr('Create account')}
        </button>
        <button type="button" onClick={() => setMode(mode === 'login' ? 'register' : 'login')} className="text-xs text-slate-400 hover:text-white">
          {mode === 'login' ? tr('New here? Create an account') : tr('Already have an account? Log in')}
        </button>
      </form>
    </div>
  );
}
