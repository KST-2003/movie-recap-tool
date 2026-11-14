import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';

// Banners made in the admin dashboard ("Posts"): 16:9 pictures the user can swipe through; they also move on by themselves.
// GET /api/posts returns only the posts that are live right now. Nothing is drawn when there are none (or the request fails).
// The title + text are drawn over the picture only when the post HAS text (many banners already carry their words in the picture).
const EVERY_MS = 6000;

export default function PostBanner({ apiBase, className = '' }) {
  const [posts, setPosts] = useState([]);
  const [at, setAt] = useState(0);
  const strip = useRef(null);
  const touched = useRef(0);

  useEffect(() => {
    let alive = true;
    axios.get(`${apiBase}/api/posts`).then((r) => { if (alive) setPosts(r.data.posts || []); }).catch(() => {});
    return () => { alive = false; };
  }, [apiBase]);

  const go = (i) => { const el = strip.current; if (el) el.scrollTo({ left: i * el.clientWidth, behavior: 'smooth' }); };
  useEffect(() => {
    if (posts.length < 2) return undefined;
    const id = setInterval(() => {
      if (document.hidden || Date.now() - touched.current < EVERY_MS) return;   // not while the user is swiping / reading
      const el = strip.current;
      if (el) go((Math.round(el.scrollLeft / el.clientWidth) + 1) % posts.length);
    }, EVERY_MS);
    return () => clearInterval(id);
  }, [posts.length]);

  if (!posts.length) return null;
  const touch = () => { touched.current = Date.now(); };
  return (
    <div className={`relative overflow-hidden rounded-[2rem] bg-white shadow-card animate-rise ${className}`}>
      <div ref={strip} onPointerDown={touch} onWheel={touch}
        onScroll={(e) => { const el = e.currentTarget; setAt(Math.round(el.scrollLeft / Math.max(1, el.clientWidth))); }}
        className="flex snap-x snap-mandatory overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {posts.map((p) => {
          const inner = (
            <>
              <img src={`${apiBase}${p.image_url}`} alt={p.title} loading="lazy" draggable="false" className="h-full w-full object-cover" />
              {p.body && (
                <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 via-black/40 to-transparent px-5 pb-6 pt-10 text-white">
                  <p className="text-base font-semibold leading-snug sm:text-lg">{p.title}</p>
                  <p className="mt-0.5 line-clamp-2 text-xs text-white/90 sm:text-sm">{p.body}</p>
                </div>
              )}
            </>
          );
          return p.link_url
            ? <a key={p.id} href={p.link_url} target="_blank" rel="noopener noreferrer" className="relative block aspect-video w-full flex-shrink-0 snap-center">{inner}</a>
            : <div key={p.id} className="relative aspect-video w-full flex-shrink-0 snap-center">{inner}</div>;
        })}
      </div>
      {posts.length > 1 && (
        <div className="pointer-events-none absolute inset-x-0 bottom-2 flex justify-center gap-1.5">
          {posts.map((p, i) => (
            <button key={p.id} type="button" aria-label={`${i + 1} / ${posts.length}`} onClick={() => { touch(); go(i); }}
              className={`pointer-events-auto h-1.5 rounded-full shadow transition-all ${i === at ? 'w-5 bg-white' : 'w-1.5 bg-white/60'}`} />
          ))}
        </div>
      )}
    </div>
  );
}
