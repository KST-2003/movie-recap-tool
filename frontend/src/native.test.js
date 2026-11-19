// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@capacitor/core', () => ({ Capacitor: { isNativePlatform: () => true, getPlatform: () => 'android' } }));
vi.mock('@capacitor/app', () => ({ App: {} }));
vi.mock('@capgo/capacitor-updater', () => ({ CapacitorUpdater: {} }));
vi.mock('@capacitor/filesystem', () => ({ Directory: {}, Filesystem: {} }));
vi.mock('@capacitor/share', () => ({ Share: {} }));
vi.mock('@capacitor/status-bar', () => ({ StatusBar: {}, Style: {} }));

import { initSafeArea } from './native.js';

afterEach(() => {
  document.documentElement.style.removeProperty('--safe-top');
  document.documentElement.style.removeProperty('--safe-bottom');
});

describe('Android safe areas', () => {
  it('keeps system insets live and reserves space before the status bar inset arrives', () => {
    initSafeArea();
    expect(document.documentElement.style.getPropertyValue('--safe-top')).toBe('max(env(safe-area-inset-top, 0px), var(--safe-area-inset-top, 32px))');
    expect(document.documentElement.style.getPropertyValue('--safe-bottom')).toBe('max(env(safe-area-inset-bottom, 0px), var(--safe-area-inset-bottom, 0px))');
  });
});
