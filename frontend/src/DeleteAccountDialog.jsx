import React, { useState } from 'react';
import axios from 'axios';
import { useI18n } from './i18n.jsx';

// "Delete my account" (App Store / Google Play require it inside the app): explains what goes, asks for the password, then removes the account.
export default function DeleteAccountDialog({ apiBase, onClose, onDeleted }) {
  const { tr, trs } = useI18n();
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError('');
    try {
      await axios.delete(`${apiBase}/api/account`, { data: { password } });
      onDeleted();
    } catch (err) {
      const d = err.response?.data?.detail;
      setError(typeof d === 'string' && err.response?.status < 500 ? trs(d) : tr('We could not delete the account just now. Please try again a little later.'));
      setBusy(false);
    }
  };
  return (
    <div className="fixed inset-0 z-[60] flex items-end sm:items-center justify-center p-0 sm:p-4" role="dialog" aria-modal="true" aria-label={tr('Delete my account')}>
      <div className="absolute inset-0 bg-ink/50 backdrop-blur-sm" onClick={busy ? undefined : onClose} />
      <form onSubmit={submit} className="relative w-full max-w-md rounded-t-[2rem] sm:rounded-[2rem] bg-white p-6 shadow-2xl animate-rise space-y-4">
        <h2 className="text-lg font-bold text-ink">{tr('Delete my account')}</h2>
        <p className="text-sm text-ink-soft">{tr('This permanently deletes your account and everything in it: your videos, presets and settings. Minutes you have left are lost and cannot be refunded. This cannot be undone.')}</p>
        <label className="block text-sm text-ink-soft">{tr('Enter your password to confirm')}
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus
            className="mt-1 w-full rounded-2xl border border-violet-200 bg-white px-3 py-2 text-sm text-ink outline-none focus:border-violet-400" />
        </label>
        {error && <p role="alert" className="rounded-2xl bg-rose-50 border border-rose-200 px-3 py-2 text-sm text-rose-700">{error}</p>}
        <div className="flex gap-2">
          <button type="button" disabled={busy} onClick={onClose} className="flex-1 rounded-2xl border border-violet-200 bg-white py-3 text-sm font-semibold text-ink-soft">{tr('Cancel')}</button>
          <button type="submit" disabled={busy || !password} className="flex-[1.5] rounded-2xl bg-rose-600 py-3 text-sm font-semibold text-white disabled:opacity-50">{busy ? tr('Deleting…') : tr('Delete my account')}</button>
        </div>
      </form>
    </div>
  );
}
