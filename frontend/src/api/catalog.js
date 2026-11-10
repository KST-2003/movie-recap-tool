import axios, { API_BASE } from './client.js';

export const getVoices = () => axios.get(`${API_BASE}/api/voices`);
export const getLooks = () => axios.get(`${API_BASE}/api/looks`);
