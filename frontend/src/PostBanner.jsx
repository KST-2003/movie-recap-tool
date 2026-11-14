import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';

// The top banner of the Create page: a strip of 16:9 slides the user swipes sideways (it also moves on by itself).
// Slide 1 = `children` (our own "What are we recapping today?" card); the next slides = the pictures admins posted in the
// dashboard ("Posts"; GET /api/posts returns only the ones that are live right now). Users see ONLY the picture: a post's
// title and text are the admin's own notes. With no posts (or a failed request) the card is simply alone.
const EVERY_MS = 6000;

export default function PostBanner({ apiBase, className = '', children }) {
  const [posts, setPosts] = useState([]);
  const [at, setAt] = useState(0);
  const strip = useRef(null);
  const touched = useRef(0);
  const count = posts.length + 1;

  useEffect(() => {
    let alive = true;
    axios.get(`${apiBase}/api/posts`).then((r) => { if (alive) setPosts(r.data.posts || []); }).catch(() => {});
    return () => { alive = false; };
  }, [apiBase]);

  const go = (i) => { const el = strip.current; if (el) el.scrollTo({ left: i * el.clientWidth, behavior: 'smooth' }); };
  useEffect(() => {
    if (count < 2) return undefined;
    const id = setInterval(() => {
      if (document.hidden || Date.now() - touched.current < EVERY_MS) return;   // not while the user is swiping / looking
      const el = strip.current;
      if (el && el.clientWidth) go((Math.round(el.scrollLeft / el.clientWidth) + 1) % count);
    }, EVERY_MS);
    return () => clearInterval(id);
  }, [count]);

  const touch = () => { touched.current = Date.now(); };
  const slide = 'relative aspect-video w-full flex-shrink-0 snap-center [scroll-snap-stop:always]';
  return (
    <div className={`relative overflow-hidden rounded-[2rem] shadow-pop animate-rise ${className}`}>
      <div ref={strip} onPointerDown={touch} onTouchMove={touch} onWheel={touch}
        onScroll={(e) => { const el = e.currentTarget; setAt(Math.round(el.scrollLeft / Math.max(1, el.clientWidth))); }}
        className="flex snap-x snap-mandatory overflow-x-auto overscroll-x-contain scroll-smooth [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className={slide}>{children}</div>
        {posts.map((p) => {
          const img = <img src={`${apiBase}${p.image_url}`} alt="" loading="lazy" draggable="false" className="h-full w-full object-cover" />;
          return p.link_url
            ? <a key={p.id} href={p.link_url} target="_blank" rel="noopener noreferrer" className={`${slide} block`}>{img}</a>
            : <div key={p.id} className={slide}>{img}</div>;
        })}
      </div>
      {count > 1 && (
        <div className="pointer-events-none absolute inset-x-0 bottom-2.5 flex justify-center gap-1.5">
          {Array.from({ length: count }, (_, i) => (
            <button key={i} type="button" aria-label={`${i + 1} / ${count}`} onClick={() => { touch(); go(i); }}
              className={`pointer-events-auto h-1.5 rounded-full shadow transition-all duration-300 ${i === at ? 'w-5 bg-white' : 'w-1.5 bg-white/60'}`} />
          ))}
        </div>
      )}
    </div>
  );
}
