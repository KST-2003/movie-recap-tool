// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Filesystem } from '@capacitor/filesystem';
import { Share } from '@capacitor/share';
import { saveToDevice } from './native.js';

vi.mock('@capacitor/core', () => ({ Capacitor: { isNativePlatform: () => true } }));
vi.mock('@capacitor/app', () => ({ App: {} }));
vi.mock('@capgo/capacitor-updater', () => ({ CapacitorUpdater: {} }));
vi.mock('@capacitor/filesystem', () => ({ Directory: { Cache: 'CACHE' }, Filesystem: { writeFile: vi.fn(), appendFile: vi.fn(), getUri: vi.fn(), deleteFile: vi.fn() } }));
vi.mock('@capacitor/share', () => ({ Share: { share: vi.fn() } }));

beforeEach(() => {
  vi.clearAllMocks();
  Filesystem.writeFile.mockResolvedValue({}); Filesystem.appendFile.mockResolvedValue({});
  Filesystem.getUri.mockResolvedValue({ uri: 'file:///cache/video.mp4' });
  Filesystem.deleteFile.mockResolvedValue({}); Share.share.mockResolvedValue({});
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

it('streams a download in bounded pieces and removes the shared copy', async () => {
  vi.useFakeTimers();
  const chunks = [new Uint8Array(3 * 1024 * 1024), new Uint8Array(5)];
  const reader = { read: vi.fn(async () => chunks.length ? { value: chunks.shift(), done: false } : { done: true }), releaseLock: vi.fn(), cancel: vi.fn() };
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body: { getReader: () => reader } })));
  const task = saveToDevice('https://example.test/video', 'video.mp4');
  await vi.waitFor(() => expect(Filesystem.appendFile).toHaveBeenCalled());
  await task;
  expect(Filesystem.writeFile).toHaveBeenCalledTimes(1);
  expect(Share.share).toHaveBeenCalledOnce();
  expect(reader.releaseLock).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(120000);
  expect(Filesystem.deleteFile).toHaveBeenCalledOnce();
});

it('rejects HTTP errors rather than saving an error page', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 403 })));
  await expect(saveToDevice('https://example.test/expired', 'video.mp4')).rejects.toThrow('Download failed (403)');
  expect(Filesystem.writeFile).not.toHaveBeenCalled();
});

it('removes a partial file if writing fails', async () => {
  const reader = { read: vi.fn(async () => ({ done: false, value: new Uint8Array(3 * 1024 * 1024) })), releaseLock: vi.fn(), cancel: vi.fn(async () => {}) };
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body: { getReader: () => reader } })));
  Filesystem.writeFile.mockRejectedValue(new Error('Storage full'));
  await expect(saveToDevice('https://example.test/video', 'video.mp4')).rejects.toThrow('Storage full');
  expect(reader.cancel).toHaveBeenCalledOnce();
  expect(Filesystem.deleteFile).toHaveBeenCalledOnce();
});
