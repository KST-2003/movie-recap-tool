// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axios from 'axios';
import HistoryPage from './HistoryPage.jsx';
import UsageDashboard from './UsageDashboard.jsx';
import TopUpPage from './TopUpPage.jsx';

vi.mock('axios', () => ({ default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('./deviceStore.js', () => ({ storedIds: vi.fn(async () => new Set()), removeVideo: vi.fn() }));
beforeEach(() => { vi.clearAllMocks(); });
afterEach(cleanup);
const pending = () => new Promise(() => {});

describe('history', () => {
  it('shows loading, then an empty history', async () => {
    let resolve;
    axios.get.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<HistoryPage apiBase="/api-root" onOpen={vi.fn()} />);
    expect(screen.getByText(/Loading/)).toBeTruthy();
    resolve({ data: { items: [], total: 0, per_page: 15, keep_result_days: 14, keep_source_days: 7 } });
    expect(await screen.findByText('No videos yet.')).toBeTruthy();
  });
  it('shows a server error', async () => {
    axios.get.mockRejectedValue({ response: { data: { detail: 'History unavailable' } } });
    render(<HistoryPage apiBase="" onOpen={vi.fn()} />);
    expect(await screen.findByText('History unavailable')).toBeTruthy();
  });
  it('opens an available video', async () => {
    axios.get.mockResolvedValue({ data: { items: [{ id: 'job1', title: 'Sample', status: 'done', video_available: true, can_edit: true, created_at: '2026-01-01T00:00:00Z', expires_at: '2099-01-01T00:00:00Z', kind: 'recap', minutes: 1, aspect: 'original' }], total: 1, per_page: 15, keep_result_days: 14, keep_source_days: 7 } });
    const open = vi.fn();
    render(<HistoryPage apiBase="" onOpen={open} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Open & edit' }));
    expect(open).toHaveBeenCalledWith('job1');
  });
  it('paginates and only deletes after confirmation', async () => {
    const row = { id: 'job1', title: 'Sample', status: 'done', video_available: true, created_at: '2026-01-01T00:00:00Z', expires_at: '2099-01-01T00:00:00Z', kind: 'recap', minutes: 1, aspect: 'original' };
    axios.get.mockResolvedValue({ data: { items: [row], total: 16, per_page: 15, keep_result_days: 14, keep_source_days: 7 } });
    axios.delete.mockResolvedValue({});
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    const user = userEvent.setup(); render(<HistoryPage apiBase="" onOpen={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Delete' }));
    expect(axios.delete).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(axios.delete).toHaveBeenCalledWith('/api/jobs/job1'));
    await user.click(screen.getByRole('button', { name: '›' }));
    await waitFor(() => expect(axios.get).toHaveBeenCalledWith('/api/jobs?page=2&per_page=15'));
    confirm.mockRestore();
  });
  it('reports a deletion error while retaining the video', async () => {
    const row = { id: 'job1', title: 'Sample', status: 'done', video_available: true, created_at: '2026-01-01T00:00:00Z', expires_at: '2099-01-01T00:00:00Z', kind: 'recap', minutes: 1, aspect: 'original' };
    axios.get.mockResolvedValue({ data: { items: [row], total: 1, per_page: 15, keep_result_days: 14, keep_source_days: 7 } });
    axios.delete.mockRejectedValue({ response: { data: { detail: 'Cannot delete' } } });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<HistoryPage apiBase="" onOpen={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    expect(await screen.findByText('Cannot delete')).toBeTruthy();
    expect(screen.getByText('Sample')).toBeTruthy();
    confirm.mockRestore();
  });
});

describe('usage', () => {
  it('shows loading and reports errors', async () => {
    axios.get.mockReturnValue(pending());
    const view = render(<UsageDashboard apiBase="" />);
    expect(screen.getByText(/Loading/)).toBeTruthy();
    view.unmount();
    axios.get.mockRejectedValue({ message: 'Usage unavailable' });
    render(<UsageDashboard apiBase="" />);
    expect(await screen.findByText('Usage unavailable')).toBeTruthy();
  });
  it('shows empty recent videos on a successful response', async () => {
    axios.get.mockResolvedValue({ data: { resets: { day: '2026-01-02', month: '2026-02-01' }, minutes_by_kind: {}, month_used_seconds: 0, used_seconds: 0, daily_minutes: 30, monthly_minutes: 100, month_videos: 0, total_videos: 0, days: Array.from({ length: 30 }, (_, i) => ({ date: `2026-01-${String(i + 1).padStart(2, '0')}`, minutes: 0 })), recent: [] } });
    render(<UsageDashboard apiBase="" />);
    expect(await screen.findByText('No videos yet.')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Show table' }));
    expect(screen.getByRole('button', { name: 'Show chart' })).toBeTruthy();
  });
  it('shows populated usage and recent video data', async () => {
    const days = Array.from({ length: 30 }, (_, i) => ({ date: `2026-01-${String(i + 1).padStart(2, '0')}`, minutes: i === 0 ? 5 : 0 }));
    axios.get.mockResolvedValue({ data: { resets: { day: '2026-01-02', month: '2026-02-01' }, minutes_by_kind: { recap: 5 }, month_used_seconds: 300, used_seconds: 300, daily_minutes: 30, monthly_minutes: 100, month_videos: 1, total_videos: 1, days, recent: [{ id: 'j1', created_at: '2026-01-01', kind: 'recap', aspect: 'original', minutes: 5, status: 'done' }] } });
    render(<UsageDashboard apiBase="" />);
    expect(await screen.findByText('Recent videos')).toBeTruthy();
    expect(screen.getAllByText('Recap voice-over').length).toBeGreaterThan(0);
    expect(screen.queryByText('No videos yet.')).toBeNull();
  });
});

describe('top up', () => {
  it('shows errors and handles a missing payment setup', async () => {
    axios.get.mockRejectedValueOnce({ message: 'Top-up unavailable' });
    const view = render(<TopUpPage apiBase="" />);
    expect(await screen.findByText('Top-up unavailable')).toBeTruthy();
    view.unmount();
    axios.get.mockResolvedValue({ data: { credit_minutes: 0, packs: [], price_per_minute: 5, qr_url: null, requests: [] } });
    render(<TopUpPage apiBase="" />);
    expect(await screen.findByText(/Top-up is not set up yet/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Send slip' }).disabled).toBe(true);
    expect(screen.getByText('No top-ups yet.')).toBeTruthy();
  });
  it('requires a pack and slip before submission', async () => {
    axios.get.mockResolvedValue({ data: { credit_minutes: 0, packs: [{ minutes: 30, price_thb: 150 }], price_per_minute: 5, qr_url: '/qr', requests: [] } });
    const { container } = render(<TopUpPage apiBase="" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /30.*150/ }));
    expect(screen.getByRole('button', { name: 'Send slip' }).disabled).toBe(true);
    await user.upload(container.querySelector('input[type=file]'), new File(['receipt'], 'receipt.pdf', { type: 'application/pdf' }));
    expect(screen.getByRole('button', { name: 'Send slip' }).disabled).toBe(false);
    expect(axios.post).not.toHaveBeenCalled();
  });
  it('shows a submission error and keeps the form available', async () => {
    axios.get.mockResolvedValue({ data: { credit_minutes: 0, packs: [{ minutes: 30, price_thb: 150 }], price_per_minute: 5, qr_url: '/qr', requests: [] } });
    axios.post.mockRejectedValue({ response: { data: { detail: 'Slip rejected' } } });
    const { container } = render(<TopUpPage apiBase="" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /30.*150/ }));
    await user.upload(container.querySelector('input[type=file]'), new File(['receipt'], 'receipt.pdf', { type: 'application/pdf' }));
    await user.click(screen.getByRole('button', { name: 'Send slip' }));
    expect(await screen.findByText('Slip rejected')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Send slip' }).disabled).toBe(false);
  });
  it('submits a selected pack and receipt and refreshes credit', async () => {
    axios.get.mockResolvedValue({ data: { credit_minutes: 0, packs: [{ minutes: 30, price_thb: 150 }], price_per_minute: 5, qr_url: '/qr', requests: [] } });
    axios.post.mockResolvedValue({ data: {} }); const changed = vi.fn();
    const { container } = render(<TopUpPage apiBase="" onChanged={changed} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /30.*150/ }));
    await user.upload(container.querySelector('input[type=file]'), new File(['receipt'], 'receipt.pdf', { type: 'application/pdf' }));
    await user.click(screen.getByRole('button', { name: 'Send slip' }));
    expect(await screen.findByText(/Sent. The admin/)).toBeTruthy();
    expect(axios.post.mock.calls[0][1].get('minutes')).toBe('30');
    await waitFor(() => expect(changed).toHaveBeenCalledOnce());
  });
  it('shows a rejected top-up and its reason', async () => {
    axios.get.mockResolvedValue({ data: { credit_minutes: 0, packs: [], price_per_minute: 5, qr_url: null, requests: [{ id: 1, created_at: '2026-01-01', minutes: 30, amount_thb: 150, status: 'rejected', admin_note: 'Unreadable slip' }] } });
    render(<TopUpPage apiBase="" />);
    expect(await screen.findByText(/Unreadable slip/)).toBeTruthy();
    expect(screen.getByText('rejected')).toBeTruthy();
  });
});
