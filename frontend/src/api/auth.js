import axios, { API_BASE } from './client.js';

// Every call here returns the raw axios response (callers read .data) so error handling stays with the caller,
// which already knows how to show a message (trs(err.response?.data?.detail)) -- duplicating that here would
// just move the same logic, not simplify anything.

export const login = (email, password) =>
  axios.post(`${API_BASE}/api/auth/login`, { email, password, cookie: true });

export const register = (email, password) =>
  axios.post(`${API_BASE}/api/auth/register`, { email, password, cookie: true });

export const me = () => axios.get(`${API_BASE}/api/auth/me`);

export const refresh = () => axios.post(`${API_BASE}/api/auth/refresh`);

export const logout = () => axios.post(`${API_BASE}/api/auth/logout`);
