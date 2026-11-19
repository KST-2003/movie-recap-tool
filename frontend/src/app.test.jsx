// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axios from 'axios';
import App from './App.jsx';
import { deviceCapability, renderFromPlan } from './deviceRenderPlan.js';
import { loadVideo } from './deviceStore.js';

vi.mock('axios', () => ({ default: { get: vi.fn(), post: vi.fn(), defaults: { headers: { common: {} } }, interceptors: { response: { use: vi.fn(), eject: vi.fn() } } } }));
vi.mock('./deviceRenderPlan.js', () => ({ deviceCapability: vi.fn(async () => ({ ok: false })), renderFromPlan: vi.fn() }));
vi.mock('./deviceStore.js', () => ({ loadVideo: vi.fn(), markUploaded: vi.fn(), saveVideo: vi.fn(), removeVideo: vi.fn(), storedIds: async () => new Set() }));
vi.mock('./Splash.jsx', () => ({ default: () => null }));
vi.mock('./PostBanner.jsx', () => ({ default: ({ children }) => <div>{children}</div> }));
vi.mock('./captionFonts.js', async (original) => ({ ...(await original()), loadCaptionFont: async () => 'sans-serif' }));

beforeEach(() => {
  localStorage.clear(); vi.clearAllMocks(); deviceCapability.mockResolvedValue({ ok: false });
  Element.prototype.scrollIntoView = vi.fn();
  window.alert = vi.fn();
  window.URL.createObjectURL = vi.fn(() => 'blob:test');
  window.URL.revokeObjectURL = vi.fn();
  axios.get.mockImplementation(async (url) => {
    if (url.includes('/voices') || url.includes('/looks')) return { data: [] };
    if (url.includes('/voice-quality')) return { data: { standard: true } };
    if (url.includes('/auth/me')) return { data: { email: 'test', remaining_seconds: 600, daily_minutes: 10, monthly_minutes: 100 } };
    return { data: {} };
  });
});
afterEach(cleanup);

describe('login', () => {
  it('clears the previous user video and ignores a stale 401 after logout', async () => {
    localStorage.setItem('token', 'old-token');
    axios.post.mockResolvedValue({ data: { token: 'new-token', email: 'new-user', remaining_seconds: 600 } });
    const user = userEvent.setup();
    const { container } = render(<App />);
    const oldInterceptor = axios.interceptors.response.use.mock.calls[0][1];
    await user.upload(container.querySelector('input[accept="video/*"]'), new File(['video'], 'private.mp4', { type: 'video/mp4' }));
    expect(screen.getByRole('button', { name: 'Remove video' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Menu' }));
    await user.click(screen.getAllByRole('button', { name: 'Log out' }).at(-1));
    await user.type(screen.getByPlaceholderText('Username'), 'new-user');
    await user.type(screen.getByPlaceholderText('Password'), 'secret');
    await user.click(screen.getByRole('button', { name: 'Log in' }));
    expect(await screen.findByText('Upload video')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Remove video' })).toBeNull();
    await expect(oldInterceptor({ response: { status: 401 }, config: { url: '/api/jobs' } })).rejects.toBeTruthy();
    expect(localStorage.getItem('token')).toBe('new-token');
  });
  it('requires both fields and shows the loading state and successful login', async () => {
    let resolve;
    axios.post.mockReturnValue(new Promise((r) => { resolve = r; }));
    const user = userEvent.setup();
    render(<App />);
    const username = screen.getByPlaceholderText('Username');
    const password = screen.getByPlaceholderText('Password');
    expect(username.required && password.required).toBe(true);
    await user.click(screen.getByRole('button', { name: 'Log in' }));
    expect(axios.post).not.toHaveBeenCalled();
    await user.type(username, 'alice');
    await user.type(password, 'secret');
    await user.click(screen.getByRole('button', { name: 'Log in' }));
    expect(screen.getByRole('button', { name: '…' }).disabled).toBe(true);
    resolve({ data: { token: 'test-token', email: 'alice', remaining_seconds: 600 } });
    await waitFor(() => expect(localStorage.getItem('token')).toBe('test-token'));
    expect(await screen.findByText('Upload video')).toBeTruthy();
  });
  it('shows an error returned by the server', async () => {
    axios.post.mockRejectedValue({ response: { data: { detail: 'Invalid credentials' } } });
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByPlaceholderText('Username'), 'alice');
    await user.type(screen.getByPlaceholderText('Password'), 'wrong');
    await user.click(screen.getByRole('button', { name: 'Log in' }));
    expect(await screen.findByText('Invalid credentials')).toBeTruthy();
  });
});

describe('page navigation', () => {
  it('shows cached history immediately when returning while refreshing in the background', async () => {
    localStorage.setItem('token', 'test-token');
    const baseGet = axios.get.getMockImplementation();
    let historyCalls = 0;
    axios.get.mockImplementation((url) => {
      if (url.includes('/api/jobs?')) {
        historyCalls += 1;
        if (historyCalls > 1) return new Promise(() => {});
        return Promise.resolve({ data: { items: [], total: 0, per_page: 15, keep_result_days: 14, keep_source_days: 7 } });
      }
      return baseGet(url);
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getAllByRole('button', { name: 'My videos' }).at(-1));
    expect(await screen.findByText('No videos yet.')).toBeTruthy();
    await user.click(screen.getAllByRole('button', { name: 'Create video' }).at(-1));
    await user.click(screen.getAllByRole('button', { name: 'My videos' }).at(-1));
    expect(screen.getByText('No videos yet.')).toBeTruthy();
    expect(historyCalls).toBeGreaterThan(1);
  });
});

describe('video creation', () => {
  it('switches between standard and high quality voices', async () => {
    localStorage.setItem('token', 'test-token'); const user = userEvent.setup(); render(<App />);
    const standard = await screen.findByRole('button', { name: /^Standard / });
    const premium = screen.getByRole('button', { name: /^High quality / });
    expect(standard.getAttribute('aria-pressed')).toBe('true');
    await user.click(premium);
    expect(premium.getAttribute('aria-pressed')).toBe('true');
    await user.click(standard);
    expect(standard.getAttribute('aria-pressed')).toBe('true');
  });
  it('accepts and removes a video and logo', async () => {
    localStorage.setItem('token', 'test-token'); const user = userEvent.setup();
    const { container } = render(<App />);
    const video = container.querySelector('input[accept="video/*"]');
    const logo = container.querySelector('input[accept="image/*"]');
    await user.upload(video, new File(['video'], 'clip.mp4', { type: 'video/mp4' }));
    await user.upload(logo, new File(['logo'], 'logo.png', { type: 'image/png' }));
    expect(screen.getByRole('button', { name: 'Remove video' })).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Remove logo' }).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: 'Remove video' }));
    expect(video.files).toHaveLength(0);
    expect(screen.queryByRole('button', { name: 'Remove video' })).toBeNull();
  });
  it('supports format, quality, mode and output selection and validates the video', async () => {
    localStorage.setItem('token', 'test-token');
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('button', { name: '9:16' }));
    expect(screen.getByText('Fit (blurred background)')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /720p/ }));
    await user.click(screen.getByRole('option', { name: /1080p/ }));
    expect(screen.getByRole('button', { name: /1080p/ })).toBeTruthy();
    await user.click(screen.getByText('Full movie / drama'));
    await user.click(screen.getByLabelText('Burmese subtitles only (original sound stays)'));
    expect(screen.getByLabelText('Burmese subtitles only (original sound stays)').checked).toBe(true);
    await user.click(screen.getByRole('button', { name: /Next/ }));
    expect(screen.getByRole('button', { name: /Back/ })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /Generate video/ }));
    expect(window.alert).toHaveBeenCalledWith('Please select a video file.');
    expect(axios.post).not.toHaveBeenCalled();
  });
});

describe('job states', () => {
  it('releases a locally opened result when the session ends', async () => {
    localStorage.setItem('token', 'test-token');
    loadVideo.mockResolvedValue({ blob: new Blob(['video']), uploaded: true });
    const baseGet = axios.get.getMockImplementation();
    const row = { id: 'local1', title: 'Saved video', status: 'done', video_available: true, created_at: '2026-01-01T00:00:00Z', expires_at: '2099-01-01T00:00:00Z', minutes: 1 };
    axios.get.mockImplementation((url) => url.includes('/api/jobs?') ? Promise.resolve({ data: { items: [row], total: 1, per_page: 15 } }) : url.endsWith('/api/jobs/local1') ? Promise.resolve({ data: { id: 'local1', result: { device_plan: {}, subtitle_url: '/captions.srt', timeline: [] } } }) : baseGet(url));
    window.scrollTo = vi.fn();
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getAllByRole('button', { name: 'My videos' }).at(-1));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    expect(await screen.findByRole('link', { name: /Download video/ })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Menu' }));
    await user.click(screen.getAllByRole('button', { name: 'Log out' }).at(-1));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test');
  });
  async function startVideo() {
    localStorage.setItem('token', 'test-token');
    const user = userEvent.setup();
    const { container } = render(<App />);
    await user.upload(container.querySelector('input[accept="video/*"]'), new File(['video'], 'sample.mp4', { type: 'video/mp4' }));
    expect([...container.querySelector('form').elements].filter((el) => el.willValidate && !el.validity.valid).map((el) => `${el.tagName}:${el.getAttribute('type')}:${el.getAttribute('min')}:${el.value}`)).toEqual([]);
    await user.click(screen.getByRole('button', { name: /Generate video/ }));
    expect(axios.post).toHaveBeenCalled();
    return user;
  }
  it('shows progress and provides cancellation while a job runs', async () => {
    axios.post.mockImplementation(async (url) => ({ data: url.endsWith('/cancel') ? {} : { job_id: 'job1' } }));
    await startVideo();
    expect(await screen.findByText('Working on your video')).toBeTruthy();
    await userEvent.click(screen.getAllByRole('button', { name: 'Cancel' })[0]);
    await waitFor(() => expect(axios.post).toHaveBeenCalledWith(expect.stringContaining('/api/jobs/job1/cancel')));
  });
  it('cancels a job requested while upload is still in progress', async () => {
    let uploadDone;
    axios.post.mockImplementation((url) => url.endsWith('/cancel') ? Promise.resolve({ data: {} }) : new Promise((resolve) => { uploadDone = resolve; }));
    await startVideo();
    await userEvent.click(screen.getAllByRole('button', { name: 'Cancel' })[0]);
    uploadDone({ data: { job_id: 'job1' } });
    await waitFor(() => expect(axios.post).toHaveBeenCalledWith(expect.stringContaining('/api/jobs/job1/cancel')));
    await waitFor(() => expect(screen.queryByText('Working on your video')).toBeNull());
  });
  it('shows an error if the server job fails', async () => {
    const baseGet = axios.get.getMockImplementation();
    axios.post.mockResolvedValue({ data: { job_id: 'job1' } });
    axios.get.mockImplementation((url) => url.endsWith('/api/jobs/job1')
      ? Promise.resolve({ data: { id: 'job1', status: 'error', progress: 30, error: 'Processing failed' } }) : baseGet(url));
    await startVideo();
    expect(await screen.findByText(/We could not complete this just now/, {}, { timeout: 6000 })).toBeTruthy();
  }, 10000);
  it('displays a job submission error', async () => {
    axios.post.mockRejectedValue({ response: { status: 400, data: { detail: 'Upload rejected' } } });
    await startVideo();
    expect(await screen.findByText('Upload rejected')).toBeTruthy();
  });
  it('offers video and subtitle downloads after a completed job', async () => {
    const baseGet = axios.get.getMockImplementation();
    axios.post.mockResolvedValue({ data: { job_id: 'job1' } });
    axios.get.mockImplementation((url) => url.endsWith('/api/jobs/job1')
      ? Promise.resolve({ data: { id: 'job1', status: 'done', progress: 100, result: { video_url: '/video.mp4', download_url: '/download.mp4', subtitle_url: '/captions.srt', timeline: [] } } })
      : baseGet(url));
    await startVideo();
    const video = await screen.findByRole('link', { name: /Download video/ }, { timeout: 6000 });
    expect(video.getAttribute('href')).toContain('/download.mp4');
    expect(screen.getByRole('link', { name: /Download subtitles/ }).getAttribute('href')).toContain('/captions.srt');
  }, 10000);
  it('shows a queued job and handles an expired result', async () => {
    const baseGet = axios.get.getMockImplementation(); let polls = 0; let finish;
    axios.post.mockResolvedValue({ data: { job_id: 'job1' } });
    axios.get.mockImplementation((url) => url.endsWith('/api/jobs/job1')
      ? (++polls === 1 ? Promise.resolve({ data: { id: 'job1', status: 'queued', progress: 0, queue_position: 2, stage: 'Queued' } }) : new Promise((resolve) => { finish = resolve; }))
      : baseGet(url));
    await startVideo();
    expect((await screen.findAllByText(/Waiting in line/, {}, { timeout: 6000 })).length).toBeGreaterThan(0);
    await waitFor(() => expect(finish).toBeTypeOf('function'), { timeout: 6000 });
    finish({ data: { id: 'job1', status: 'done', progress: 100, result: { expired: true } } });
    expect(await screen.findByText(/We could not complete this just now/, {}, { timeout: 6000 })).toBeTruthy();
  }, 12000);
  it('falls back to a server render when device rendering fails', async () => {
    deviceCapability.mockResolvedValue({ ok: true });
    renderFromPlan.mockRejectedValue(new Error('device failed'));
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, blob: async () => new Blob(['audio']) });
    const baseGet = axios.get.getMockImplementation();
    axios.post.mockImplementation(async (url) => ({ data: { job_id: url.endsWith('/rerender') ? 'job2' : 'job1' } }));
    axios.get.mockImplementation((url) => url.endsWith('/api/jobs/job1')
      ? Promise.resolve({ data: { id: 'job1', status: 'done', progress: 100, result: { device_plan: {}, audio_url: '/audio' } } })
      : url.endsWith('/api/jobs/job2')
        ? Promise.resolve({ data: { id: 'job2', status: 'done', progress: 100, result: { video_url: '/video.mp4', download_url: '/download.mp4', subtitle_url: '/captions.srt', timeline: [] } } })
        : baseGet(url));
    await startVideo();
    expect(await screen.findByRole('link', { name: /Download video/ }, { timeout: 9000 })).toBeTruthy();
    expect(renderFromPlan).toHaveBeenCalledTimes(2);
    expect(axios.post).toHaveBeenCalledWith(expect.stringContaining('/api/jobs/job1/rerender'), expect.objectContaining({ segments: [], device_render: false, fallback: true }));
    fetchMock.mockRestore();
  }, 15000);
  it.each([false, true])('reopens a history result (expired: %s)', async (expired) => {
    localStorage.setItem('token', 'test-token');
    const baseGet = axios.get.getMockImplementation();
    const row = { id: 'job1', title: 'Saved video', status: 'done', video_available: true, created_at: '2026-01-01T00:00:00Z', expires_at: '2099-01-01T00:00:00Z', kind: 'recap', minutes: 1, aspect: 'original' };
    axios.get.mockImplementation((url) => url.includes('/api/jobs?')
      ? Promise.resolve({ data: { items: [row], total: 1, per_page: 15, keep_result_days: 14, keep_source_days: 7 } })
      : url.endsWith('/api/jobs/job1') ? Promise.resolve({ data: { id: 'job1', result: expired ? { expired: true } : { video_url: '/video.mp4', download_url: '/download.mp4', subtitle_url: '/captions.srt', timeline: [] } } }) : baseGet(url));
    window.scrollTo = vi.fn(); const user = userEvent.setup(); render(<App />);
    await user.click(screen.getAllByRole('button', { name: 'My videos' }).at(-1));
    await user.click(await screen.findByRole('button', { name: 'Open' }));
    if (expired) expect(await screen.findByText('This result has expired. Please generate it again.')).toBeTruthy();
    else expect(await screen.findByRole('link', { name: /Download video/ })).toBeTruthy();
  });
  it('shows an error when an editor rerender request fails', async () => {
    const baseGet = axios.get.getMockImplementation();
    axios.post.mockImplementation((url) => url.endsWith('/rerender') ? Promise.reject({ response: { status: 400, data: { detail: 'Rerender refused' } } }) : Promise.resolve({ data: { job_id: 'job1' } }));
    axios.get.mockImplementation((url) => url.endsWith('/api/jobs/job1')
      ? Promise.resolve({ data: { id: 'job1', status: 'done', progress: 100, result: { video_url: '/video.mp4', download_url: '/download.mp4', subtitle_url: '/captions.srt', timeline: [], project: { source_duration: 10, output: 'dub', segments: [{ id: 1, start: 0, text: 'Original', audio_dur: 2, applied_tempo: 1 }] } } } }) : baseGet(url));
    const user = await startVideo();
    const line = await screen.findByPlaceholderText('Burmese text for this line', {}, { timeout: 6000 });
    await user.clear(line); await user.type(line, 'Changed');
    await user.click(screen.getByRole('button', { name: /Apply changes & re-render/ }));
    expect(await screen.findByText('Rerender refused')).toBeTruthy();
  }, 12000);
});
