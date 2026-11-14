import React from 'react';

// Recat's mascot: the owner's art (white cat with 3D glasses in a popcorn bucket), `public/recat.webp` (400x400, transparent;
// taken from docs/loading_screen.html). `still` turns the floating off.
export default function Mascot({ className = 'h-12 w-12', still = false }) {
  return <img src="/recat.webp" alt="" aria-hidden="true" draggable={false} className={`${className} select-none object-contain ${still ? '' : 'animate-floaty'}`} />;
}

// The word mark: mascot + "Recat Studio" (sidebar, phone top bar, account sheet).
export function Brand({ size = 'text-xl', icon = 'h-10 w-10' }) {
  return (
    <span className="inline-flex items-center gap-2">
      <Mascot className={icon} />
      <span className={`${size} font-bold tracking-tight whitespace-nowrap`}>
        <span className="bg-gradient-to-r from-violet-600 to-pink-500 bg-clip-text text-transparent">Recat</span>{' '}
        <span className="text-amber-500">Studio</span>
      </span>
    </span>
  );
}
