import axios from 'axios';

export const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

// The login session is an httpOnly cookie set by the API: JavaScript cannot read it, so a script injected into this page
// cannot steal it (the old token in localStorage could be). This module keeps the CSRF token, in memory only; it is sent
// with every request that changes something. The interceptor is registered once, at module load, outside React -- it has
// to be, since axios interceptors are a singleton concept, not per-component -- so csrfToken lives here, not in a hook.
axios.defaults.withCredentials = true;
let csrfToken = '';

axios.interceptors.request.use((config) => {
  if (csrfToken && !/^(get|head|options)$/i.test(config.method || 'get')) config.headers['X-CSRF-Token'] = csrfToken;
  return config;
});

// Keeps the previous token if `token` is falsy, rather than wiping it -- every real server response that carries a
// session (login/register/refresh/me with cookie:true) always includes csrf_token, so this only matters as a safety
// net against a malformed response, and "don't silently drop a good token" is the safer default for that case.
export const setCsrfToken = (token) => { if (token) csrfToken = token; };
export const clearCsrfToken = () => { csrfToken = ''; };

export const absUrl = (u) => (u.startsWith('http') ? u : API_BASE + u);

export default axios;
