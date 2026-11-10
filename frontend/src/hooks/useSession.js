import { useEffect, useState } from 'react';
import axios from '../api/client.js';
import { clearCsrfToken, setCsrfToken } from '../api/client.js';
import * as authApi from '../api/auth.js';

// Session state: who is signed in, and keeping that session alive. The server deletes the httpOnly cookie on logout
// (JavaScript cannot touch it); this hook only ever clears its OWN in-memory copy of the CSRF token and state.
export default function useSession() {
  const [signedIn, setSignedIn] = useState(null);   // null = still asking the server, false = sign-in screen, true = in
  const [account, setAccount] = useState(null);     // { email, daily_minutes, remaining_seconds, ... }

  const logout = (callServer = true) => {
    clearCsrfToken();
    setSignedIn(false);
    setAccount(null);
    if (callServer) authApi.logout().catch(() => {});
  };

  const onAuth = (data) => {
    setCsrfToken(data.csrf_token);
    setAccount(data);
    setSignedIn(true);
  };

  const refreshAccount = () => authApi.me().then((r) => { setCsrfToken(r.data.csrf_token); setAccount(r.data); }).catch(() => {});

  useEffect(() => {
    const id = axios.interceptors.response.use((r) => r, (err) => {
      if (err.response?.status === 401 && !String(err.config?.url).includes('/api/auth/')) logout(false);
      return Promise.reject(err);
    });
    return () => axios.interceptors.response.eject(id);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Already signed in? The cookie survives a page reload, the CSRF token in memory does not: /me hands it out again.
  useEffect(() => {
    try { localStorage.removeItem('token'); } catch (e) { /* the old place of the token: nothing may stay there */ }
    authApi.me().then((r) => { setCsrfToken(r.data.csrf_token); setAccount(r.data); setSignedIn(true); }).catch(() => setSignedIn(false));
  }, []);

  // Keep the session alive while the app is open (admin accounts get 60-minute sessions): renew every 10 minutes and when the tab comes back.
  // A 401 here means the session was cancelled (password reset, "log out everywhere") or is too old: back to the sign-in screen.
  useEffect(() => {
    if (!signedIn) return undefined;
    let stopped = false;
    const renew = () => authApi.refresh().then((r) => {
      if (!stopped) setCsrfToken(r.data.csrf_token);
    }).catch((err) => { if (err.response?.status === 401) logout(false); });
    const timer = setInterval(renew, 10 * 60 * 1000);
    const onVisible = () => { if (document.visibilityState === 'visible') renew(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => { stopped = true; clearInterval(timer); document.removeEventListener('visibilitychange', onVisible); };
  }, [signedIn]); // eslint-disable-line react-hooks/exhaustive-deps

  return { signedIn, account, logout, onAuth, refreshAccount };
}
