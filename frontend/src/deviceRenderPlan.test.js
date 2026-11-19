// @vitest-environment jsdom
import { expect, it } from 'vitest';
import { renderFromPlan } from './deviceRenderPlan.js';

it('rejects a render estimated to exceed the device memory budget before encoding', async () => {
  const plan = { out: [1080, 1920], duration: 3600 };
  await expect(renderFromPlan(new Blob(['video']), plan, new Blob(['audio']), null)).rejects.toThrow('Video is too large for on-device rendering');
});
