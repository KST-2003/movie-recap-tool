// Finished videos that were drawn on THIS device, kept in the browser's own storage (IndexedDB) so "My videos" can open them
// again without downloading. A copy is also uploaded to the server; both are removed after KEEP_DAYS.
// The browser may delete this storage on its own (Safari: sites not visited for ~7 days, any browser when space is low), and it
// is per device + per browser: every call fails soft, the server copy is the fallback.
export const KEEP_DAYS = 14;
const DB = 'recat-videos', STORE = 'videos';

function open() {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') { reject(new Error('no storage')); return; }
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: 'id' });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
const run = async (mode, fn) => {
  const db = await open();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const req = fn(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(req?.result);
      tx.onerror = tx.onabort = () => reject(tx.error || new Error('storage failed'));
    });
  } finally { db.close(); }
};

/** Keep a finished video; `uploaded` = the server has its copy too. Returns false when the device refused (no space, private window). */
export async function saveVideo(id, blob, uploaded = false) {
  try { await purgeOld(); await run('readwrite', (s) => s.put({ id, blob, at: Date.now(), uploaded })); return true; } catch (e) { return false; }
}
export async function markUploaded(id) {
  try { const row = await run('readonly', (s) => s.get(id)); if (row) await run('readwrite', (s) => s.put({ ...row, uploaded: true })); } catch (e) { /* optional */ }
}
/** { blob, uploaded } or null. */
export async function loadVideo(id) {
  try { const row = await run('readonly', (s) => s.get(id)); return row && row.blob ? { blob: row.blob, uploaded: !!row.uploaded } : null; } catch (e) { return null; }
}
export async function removeVideo(id) { try { await run('readwrite', (s) => s.delete(id)); } catch (e) { /* optional */ } }
/** Ids of the videos stored on this device (after removing the ones past their keeping time). */
export async function storedIds() {
  try { await purgeOld(); return new Set(await run('readonly', (s) => s.getAllKeys())); } catch (e) { return new Set(); }
}
async function purgeOld() {
  const rows = await run('readonly', (s) => s.getAll());
  const old = (rows || []).filter((r) => Date.now() - r.at > KEEP_DAYS * 86400000).map((r) => r.id);
  if (old.length) await run('readwrite', (s) => { old.forEach((id) => s.delete(id)); });
}
