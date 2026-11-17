// Helpers for the Capacitor shell (iPhone / Android app). On the normal website `isNative` is false and nothing here is used.
import { Capacitor } from '@capacitor/core';
import { Directory, Filesystem } from '@capacitor/filesystem';
import { Share } from '@capacitor/share';

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
  const blob = await (await fetch(url)).blob();
  const path = `recat_${Date.now()}_${filename}`;
  for (let off = 0, first = true; off < blob.size; off += CHUNK, first = false) {
    const data = await toBase64(blob.slice(off, off + CHUNK));
    if (first) await Filesystem.writeFile({ path, data, directory: Directory.Cache });
    else await Filesystem.appendFile({ path, data, directory: Directory.Cache });
  }
  if (blob.size === 0) await Filesystem.writeFile({ path, data: '', directory: Directory.Cache });
  const { uri } = await Filesystem.getUri({ path, directory: Directory.Cache });
  try {
    await Share.share({ title: title || filename, files: [uri], dialogTitle: title || filename });
  } finally {
    // the shared copy is only needed while the share sheet is open
    setTimeout(() => { Filesystem.deleteFile({ path, directory: Directory.Cache }).catch(() => {}); }, 120000);
  }
}
