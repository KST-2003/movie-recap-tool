// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Filesystem } from '@capacitor/filesystem';

const state = { platform: 'ios', plugin: true };
const Media = { saveVideo: vi.fn(), getAlbumsPath: vi.fn(), createAlbum: vi.fn() };
vi.mock('@capacitor/core', () => ({ Capacitor: { isNativePlatform: () => true, getPlatform: () => state.platform, isPluginAvailable: () => state.plugin } }));
vi.mock('@capacitor/app', () => ({ App: {} }));
vi.mock('@capgo/capacitor-updater', () => ({ CapacitorUpdater: {} }));
vi.mock('@capacitor/share', () => ({ Share: { share: vi.fn() } }));
vi.mock('@capacitor/filesystem', () => ({ Directory: { Cache: 'CACHE' }, Filesystem: { writeFile: vi.fn(), appendFile: vi.fn(), getUri: vi.fn(), deleteFile: vi.fn() } }));
vi.mock('@capacitor-community/media', () => ({ Media }));
const { saveVideoToPhotos } = await import('./native.js');

beforeEach(() => {
  vi.clearAllMocks();
  state.platform = 'ios'; state.plugin = true;
  Filesystem.writeFile.mockResolvedValue({}); Filesystem.appendFile.mockResolvedValue({});
  Filesystem.getUri.mockResolvedValue({ uri: 'file:///cache/v.mp4' }); Filesystem.deleteFile.mockResolvedValue({});
  Media.saveVideo.mockResolvedValue({}); Media.getAlbumsPath.mockResolvedValue({ path: '/storage/emulated/0/Pictures' }); Media.createAlbum.mockResolvedValue();
  const reader = { read: vi.fn(async () => (reader.n++ ? { done: true } : { value: new Uint8Array(10), done: false })), releaseLock: vi.fn(), cancel: vi.fn(), n: 0 };
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body: { getReader: () => reader } })));
});
afterEach(() => { vi.unstubAllGlobals(); });

it('iOS: the video goes into Photos with no share sheet', async () => {
  expect(await saveVideoToPhotos('https://x.test/v', 'v.mp4')).toBe(true);
  expect(Media.saveVideo).toHaveBeenCalledWith({ path: 'file:///cache/v.mp4' });
  expect(Media.createAlbum).not.toHaveBeenCalled();
});

it('Android: saved into the Recat album under the albums path', async () => {
  state.platform = 'android';
  expect(await saveVideoToPhotos('https://x.test/v', 'v.mp4')).toBe(true);
  expect(Media.createAlbum).toHaveBeenCalledWith({ name: 'Recat' });
  const arg = Media.saveVideo.mock.calls[0][0];
  expect(arg.albumIdentifier).toBe('/storage/emulated/0/Pictures/Recat');
  expect(arg.path).toBe('file:///cache/v.mp4');
});

it('Android: an album that already exists is fine', async () => {
  state.platform = 'android';
  Media.createAlbum.mockRejectedValue(new Error('Album already exists'));
  expect(await saveVideoToPhotos('https://x.test/v', 'v.mp4')).toBe(true);
});

it('an app build without the plugin, or a refused / failed save, returns false so the share sheet is used', async () => {
  state.plugin = false;
  expect(await saveVideoToPhotos('https://x.test/v', 'v.mp4')).toBe(false);
  expect(fetch).not.toHaveBeenCalled();
  state.plugin = true;
  Media.saveVideo.mockRejectedValue(new Error('Permission denied'));
  expect(await saveVideoToPhotos('https://x.test/v', 'v.mp4')).toBe(false);
});
