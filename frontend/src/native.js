// Helpers for the Capacitor shell (iPhone / Android app). On the normal website `isNative` is false and nothing here is used.
import { Capacitor } from '@capacitor/core';
import { App as CapApp } from '@capacitor/app';
import { CapacitorUpdater } from '@capgo/capacitor-updater';
import { Directory, Filesystem } from '@capacitor/filesystem';
import { Share } from '@capacitor/share';
import { StatusBar, Style } from '@capacitor/status-bar';

export const isNative = Capacitor.isNativePlatform();

const CHUNK = 3 * 1024 * 1024;   // 3 MB per piece: a 100 MB video is never held as one huge base64 string

const toBase64 = (blob) => new Promise((resolve, reject) => {
  const r = new FileReader();
  r.onloadend = () => resolve(String(r.result).split(',')[1] || '');
  r.onerror = () => reject(r.error);
  r.readAsDataURL(blob);
});

// Saves a video / subtitle file (a https: address or a blob: address) and opens the system share sheet,
// where the user taps "Save Video" / "Save to Files". WKWebView ignores <a download>, so the web way does not work there.
export async function saveToDevice(url, filename, title) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Download failed (${response.status})`);
  const path = `recat_${Date.now()}_${filename}`;
  let first = true;
  let shared = false;
  let reader;
  try {
    const write = async (blob) => {
      const data = await toBase64(blob);
      if (first) await Filesystem.writeFile({ path, data, directory: Directory.Cache });
      else await Filesystem.appendFile({ path, data, directory: Directory.Cache });
      first = false;
    };
    if (response.body?.getReader) {
      reader = response.body.getReader();
      let parts = [], size = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        for (let offset = 0; offset < value.length;) {
          const take = Math.min(CHUNK - size, value.length - offset);
          parts.push(value.subarray(offset, offset + take)); size += take; offset += take;
          if (size === CHUNK) { await write(new Blob(parts)); parts = []; size = 0; }
        }
      }
      if (size) await write(new Blob(parts));
    } else {
      // Older WebViews may not expose streaming responses.
      const blob = await response.blob();
      for (let off = 0; off < blob.size; off += CHUNK) await write(blob.slice(off, off + CHUNK));
    }
    if (first) await Filesystem.writeFile({ path, data: '', directory: Directory.Cache });
    const { uri } = await Filesystem.getUri({ path, directory: Directory.Cache });
    await Share.share({ title: title || filename, files: [uri], dialogTitle: title || filename });
    shared = true;
  } finally {
    if (reader) { if (!shared) await reader.cancel().catch(() => {}); reader.releaseLock(); }
    const remove = () => { Filesystem.deleteFile({ path, directory: Directory.Cache }).catch(() => {}); };
    if (shared) setTimeout(remove, 120000); else remove();
  }
}

// ---- OTA (over-the-air) web updates: see backend/ota.py and frontend/scripts/publish-ota.mjs ----
// The plugin checks our server by itself (capacitor.config.json -> CapacitorUpdater.updateUrl) and downloads a new bundle; the app must say it started
// fine with notifyAppReady(), otherwise the plugin goes back to the previous bundle after appReadyTimeout.
export async function initOta() {
  if (!isNative) return;
  try { await CapacitorUpdater.notifyAppReady(); } catch (e) { console.warn('OTA: notifyAppReady failed', e); }
}

/** "1.1.0 (build 3) · bundle ota-20261117-1500" for the account box (support: which web bundle runs). null on the website. */
export async function nativeVersionLabel() {
  if (!isNative) return null;
  try {
    const [info, cur] = await Promise.all([CapApp.getInfo(), CapacitorUpdater.current()]);
    const bundle = cur?.bundle?.version;
    return `${info.version} (${info.build})${bundle && bundle !== 'builtin' ? ` · ${bundle}` : ''}`;
  } catch (e) { return null; }
}

/** The status bar is transparent (the page shows through), so only the TEXT colour matters: light text on the dark opening screen, dark text everywhere else. */
export async function statusBarOnDark(onDark) {
  if (!isNative) return;
  try { await StatusBar.setStyle({ style: onDark ? Style.Dark : Style.Light }); } catch (e) { /* older app build / Android without the plugin call: ignore */ }
}

/** Phone app: the page runs under the transparent status bar, so it must keep its own content clear of the clock / notch / home bar.
 *  Android keeps CSS references live because Capacitor can supply its insets after the page starts.
 *  On iOS, read the web view insets and fall back to the screen size when they are unavailable. */
export function initSafeArea() {
  if (!isNative) return;
  if (Capacitor.getPlatform() === 'android') {
    // Capacitor updates these variables when Android's system-bar insets arrive or change.
    // Until then, leave room for the status bar so controls do not start beneath it.
    document.documentElement.style.setProperty('--safe-top', 'max(env(safe-area-inset-top, 0px), var(--safe-area-inset-top, 32px))');
    document.documentElement.style.setProperty('--safe-bottom', 'max(env(safe-area-inset-bottom, 0px), var(--safe-area-inset-bottom, 0px))');
    return;
  }
  try {
    const probe = document.createElement('div');
    probe.style.cssText = 'position:fixed;visibility:hidden;pointer-events:none;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)';
    document.body.appendChild(probe);
    const cs = getComputedStyle(probe);
    let top = parseFloat(cs.paddingTop) || 0, bottom = parseFloat(cs.paddingBottom) || 0;
    probe.remove();
    const ios = Capacitor.getPlatform() === 'ios', h = Math.max(screen.height, screen.width);
    if (ios && !top) top = h >= 852 ? 59 : h >= 812 ? 47 : 20;   // Dynamic Island / notch / old home-button iPhones
    if (ios && !bottom) bottom = h >= 812 ? 34 : 0;
    document.documentElement.style.setProperty('--safe-top', `${top}px`);
    document.documentElement.style.setProperty('--safe-bottom', `${bottom}px`);
  } catch (e) { /* keep the CSS env() values */ }
}
