// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axios from 'axios';
import App from './App.jsx';

import { App as CapApp } from '@capacitor/app';
vi.mock('@capacitor/core', () => ({ Capacitor: { getPlatform: () => 'android' } }));
vi.mock('@capacitor/app', () => ({ App: { addListener: vi.fn(async () => ({ remove: vi.fn() })), minimizeApp: vi.fn(async () => {}) } }));
vi.mock('./native.js', () => ({ isNative: true, saveToDevice: vi.fn(), nativeVersionLabel: async () => null }));
vi.mock('axios', () => ({ default: { get: vi.fn(), post: vi.fn(), defaults: { headers: { common: {} } }, interceptors: { response: { use: vi.fn(), eject: vi.fn() } } } }));
vi.mock('./deviceRenderPlan.js', () => ({ deviceCapability: async () => ({ ok: false }), renderFromPlan: vi.fn() }));
vi.mock('./deviceStore.js', () => ({ loadVideo: vi.fn(), markUploaded: vi.fn(), saveVideo: vi.fn(), removeVideo: vi.fn(), storedIds: async () => new Set() }));
vi.mock('./Splash.jsx', () => ({ default: () => null }));
vi.mock('./PostBanner.jsx', () => ({ default: ({ children }) => <div>{children}</div> }));

afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks(); });

it('uses Android back to leave a page, step backward, then minimize', async () => {
  localStorage.setItem('token', 'token');
  Element.prototype.scrollIntoView = vi.fn();
  axios.get.mockImplementation(async (url) => {
    if (url.includes('/jobs?')) return { data: { items: [], total: 0, per_page: 15, keep_result_days: 14, keep_source_days: 7 } };
    if (url.includes('/voices') || url.includes('/looks')) return { data: [] };
    if (url.includes('/auth/me')) return { data: { email: 'user', remaining_seconds: 60, daily_minutes: 1, monthly_minutes: 1 } };
    return { data: {} };
  });
  const user = userEvent.setup(); render(<App />);
  await user.click(screen.getAllByRole('button', { name: 'My videos' }).at(-1));
  expect(await screen.findByText('No videos yet.')).toBeTruthy();
  await waitFor(() => expect(CapApp.addListener).toHaveBeenCalled());
  await act(async () => CapApp.addListener.mock.calls.at(-1)[1]());
  expect(screen.getByText('Upload video')).toBeTruthy();
  await user.click(screen.getByRole('button', { name: /Next/ }));
  expect(screen.getByRole('button', { name: /Back/ })).toBeTruthy();
  await act(async () => CapApp.addListener.mock.calls.at(-1)[1]());
  expect(screen.queryByRole('button', { name: /Back/ })).toBeNull();
  await user.click(screen.getByRole('button', { name: 'Menu' }));
  expect(screen.getByRole('button', { name: 'Close menu' })).toBeTruthy();
  await act(async () => CapApp.addListener.mock.calls.at(-1)[1]());
  expect(screen.queryByRole('button', { name: 'Close menu' })).toBeNull();
  await act(async () => CapApp.addListener.mock.calls.at(-1)[1]());
  expect(CapApp.minimizeApp).toHaveBeenCalledOnce();
});
