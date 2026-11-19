// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { IDBFactory, IDBKeyRange } from 'fake-indexeddb';
import { Blob as NodeBlob } from 'node:buffer';
import { KEEP_DAYS, loadVideo, markUploaded, saveVideo, storedIds } from './deviceStore.js';

afterEach(() => vi.unstubAllGlobals());

it('migrates old video storage and removes expired entries without losing recent videos', async () => {
  const dbFactory = new IDBFactory();
  vi.stubGlobal('indexedDB', dbFactory); vi.stubGlobal('IDBKeyRange', IDBKeyRange);
  await new Promise((resolve, reject) => {
    const req = dbFactory.open('recat-videos', 1);
    req.onupgradeneeded = () => req.result.createObjectStore('videos', { keyPath: 'id' });
    req.onsuccess = () => {
      const db = req.result; const tx = db.transaction('videos', 'readwrite');
      tx.objectStore('videos').put({ id: 'expired', blob: new NodeBlob(['old']), at: Date.now() - (KEEP_DAYS + 1) * 86400000 });
      tx.objectStore('videos').put({ id: 'recent', blob: new NodeBlob(['new']), at: Date.now() });
      tx.oncomplete = () => { db.close(); resolve(); }; tx.onerror = () => reject(tx.error);
    };
    req.onerror = () => reject(req.error);
  });
  expect(await storedIds()).toEqual(new Set(['recent']));
  expect(await loadVideo('expired')).toBeNull();
  expect((await loadVideo('recent')).blob.size).toBe(3);
  expect(await saveVideo('another', new NodeBlob(['x']))).toBe(true);
  await markUploaded('another');
  expect((await loadVideo('another')).uploaded).toBe(true);
});
