// @vitest-environment jsdom
import { expect, it, vi } from 'vitest';
vi.mock('mediabunny', () => ({ ALL_FORMATS: [], BlobSource: class {}, Input: class { getPrimaryVideoTrack() { return null; } dispose() {} }, canEncodeVideo: async () => true }));
vi.mock('./captionFonts.js', () => ({ DEFAULT_CAPTION_STYLE: {}, loadCaptionFont: async () => 'sans', rgba: () => '' }));
import { Input } from 'mediabunny';
import { renderFromPlan } from './deviceRenderPlan.js';
it('disposes the video input when a source cannot be decoded', async () => {
  const dispose = vi.spyOn(Input.prototype, 'dispose');
  await expect(renderFromPlan(new Blob(['video']), { out: [720, 1280], duration: 1 }, new Blob(['audio']), null)).rejects.toThrow('No video track');
  expect(dispose).toHaveBeenCalledOnce();
});
