// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axios from 'axios';
import App from './App.jsx';
import { deviceCapability, renderFromPlan } from './deviceRenderPlan.js';

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

describe('video creation', () => {
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
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ blob: async () => new Blob(['audio']) });
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
    expect(axios.post).toHaveBeenCalledWith(expect.stringContaining('/api/jobs/job1/rerender'), { segments: [], device_render: false });
    fetchMock.mockRestore();
  }, 15000);
});
