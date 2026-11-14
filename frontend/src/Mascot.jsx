import React from 'react';

// Recat's mascot: a white cat with 3D glasses in a popcorn bucket (drawn by us as SVG; public/recat.svg is the same picture
// without motion, used as the browser-tab icon). `still` turns the floating off (small sizes).
export default function Mascot({ className = 'h-12 w-12', still = false }) {
  return (
    <svg viewBox="0 0 120 120" className={`${className} ${still ? '' : 'animate-floaty'}`} aria-hidden="true">
  <ellipse cx="60" cy="112" rx="34" ry="4" fill="#8B5CF6" opacity="0.18"/>
  <g className="animate-kernel origin-center" style={{ transformBox: 'fill-box' }}><path d="M17 58c-4-1-5-7-1-8 0-5 7-5 8-1 4-1 6 4 3 6 1 4-5 6-7 3z" fill="#FFF3C4" stroke="#F2C94C" strokeWidth="1.5"/></g>
  <g className="animate-kernel origin-center" style={{ transformBox: 'fill-box', animationDelay: '0.7s' }}><path d="M98 40c-3-2-2-7 2-7 1-4 7-3 7 1 4 0 5 5 2 6 0 4-6 5-8 2z" fill="#FFF3C4" stroke="#F2C94C" strokeWidth="1.5"/></g>
  <g className="animate-kernel origin-center" style={{ transformBox: 'fill-box', animationDelay: '1.3s' }}><path d="M102 86c-3-1-3-6 0-7 1-4 6-3 7 0 3 0 4 5 1 6 0 3-5 4-8 1z" fill="#FFF3C4" stroke="#F2C94C" strokeWidth="1.5"/></g>
  <path d="M33 34 L38 12 L54 26 Z" fill="#fff" stroke="#C4A6FF" strokeWidth="2" strokeLinejoin="round"/>
  <path d="M87 34 L82 12 L66 26 Z" fill="#fff" stroke="#C4A6FF" strokeWidth="2" strokeLinejoin="round"/>
  <path d="M39 29 L41 19 L48 26 Z" fill="#FFB6D9"/><path d="M81 29 L79 19 L72 26 Z" fill="#FFB6D9"/>
  <ellipse cx="60" cy="52" rx="33" ry="29" fill="#fff" stroke="#C4A6FF" strokeWidth="2"/>
  <ellipse cx="38" cy="62" rx="5" ry="3" fill="#FFB6D9" opacity="0.8"/><ellipse cx="82" cy="62" rx="5" ry="3" fill="#FFB6D9" opacity="0.8"/>
  <path d="M27 44 H93" stroke="#2B2440" strokeWidth="4" strokeLinecap="round"/>
  <g className="animate-blink" style={{ transformBox: 'fill-box', transformOrigin: 'center' }}><rect x="35" y="40" width="22" height="15" rx="5" fill="#4F7BFF" stroke="#2B2440" strokeWidth="3"/>
  <rect x="63" y="40" width="22" height="15" rx="5" fill="#FF5C7A" stroke="#2B2440" strokeWidth="3"/>
  <path d="M39 44 l5 0" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" opacity="0.8"/><path d="M67 44 l5 0" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" opacity="0.8"/></g>
  <path d="M57 62 q3 3 6 0" fill="#FF8FB8" stroke="#FF8FB8" strokeWidth="1.5" strokeLinejoin="round"/>
  <path d="M54 67 q3 4 6 0 q3 4 6 0" fill="none" stroke="#2B2440" strokeWidth="2" strokeLinecap="round"/>
  <path d="M30 74 q-2-7 5-8 1-6 8-3 4-5 9-1 5-5 10 0 5-4 9 1 7-3 8 3 7 1 5 8z" fill="#FFF3C4" stroke="#F2C94C" strokeWidth="1.5"/>
  <path d="M27 74 H93 L86 108 Q60 114 34 108 Z" fill="#fff" stroke="#C4A6FF" strokeWidth="2" strokeLinejoin="round"/>
  <path d="M38 74 h11 l2 36 q-6 0-9-1z M55 74 h10 l-1 37 h-8z M71 74 h11 l-4 35 q-4 1-9 1z" fill="#FF6B81"/>
  <ellipse cx="42" cy="76" rx="8" ry="6" fill="#fff" stroke="#C4A6FF" strokeWidth="2"/><ellipse cx="78" cy="76" rx="8" ry="6" fill="#fff" stroke="#C4A6FF" strokeWidth="2"/>
    </svg>
  );
}

// The word mark: mascot + "Recat".
export function Brand({ size = 'text-xl', icon = 'h-10 w-10' }) {
  return (
    <span className="inline-flex items-center gap-2">
      <Mascot className={icon} />
      <span className={`${size} font-bold tracking-tight bg-gradient-to-r from-violet-600 to-pink-500 bg-clip-text text-transparent`}>Recat</span>
    </span>
  );
}
