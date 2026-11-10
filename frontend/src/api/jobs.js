import axios, { API_BASE } from './client.js';

export const createJob = (formData, onUploadProgress) =>
  axios.post(`${API_BASE}/api/jobs`, formData, { onUploadProgress });

export const getJob = (id) => axios.get(`${API_BASE}/api/jobs/${id}`);

export const cancelJob = (id) => axios.post(`${API_BASE}/api/jobs/${id}/cancel`);

export const rerender = (jobId, body) => axios.post(`${API_BASE}/api/jobs/${jobId}/rerender`, body);

// responseType 'blob': the response IS audio bytes, not JSON. 120s timeout: a real TTS request can be slow.
export const previewLine = (jobId, body) =>
  axios.post(`${API_BASE}/api/jobs/${jobId}/preview-line`, body, { responseType: 'blob', timeout: 120000 });
