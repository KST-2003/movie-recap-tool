/** @type {import('tailwindcss').Config} */
// Recat theme (2026-11-14): primary = violet-500 #8B5CF6, lavender #C4A6FF, blush #FFB6D9, popcorn #FFD976, page #F7F4FF, cards white.
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        page: '#F7F4FF',
        ink: { DEFAULT: '#2B2440', soft: '#6B6385', faint: '#9A93B5' },
        lavender: '#C4A6FF',
        blush: '#FFB6D9',
        popcorn: '#FFD976',
      },
      fontFamily: {
        sans: ['Poppins', '"Noto Sans Myanmar"', '"Myanmar Sangam MN"', '"Myanmar Text"', 'Padauk', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        card: '0 10px 30px -12px rgba(139, 92, 246, 0.25)',
        pop: '0 8px 20px -6px rgba(139, 92, 246, 0.55)',
      },
      keyframes: {
        rise: { from: { opacity: 0, transform: 'translateY(14px) scale(0.98)' }, to: { opacity: 1, transform: 'none' } },
        floaty: { '0%,100%': { transform: 'translateY(0) rotate(-2deg)' }, '50%': { transform: 'translateY(-7px) rotate(2deg)' } },
        drift: { '0%,100%': { transform: 'translateX(0)' }, '50%': { transform: 'translateX(14px)' } },
        pop: { '0%': { transform: 'scale(0.6)', opacity: 0 }, '60%': { transform: 'scale(1.12)', opacity: 1 }, '100%': { transform: 'scale(1)', opacity: 1 } },
        blink: { '0%,92%,100%': { transform: 'scaleY(1)' }, '96%': { transform: 'scaleY(0.1)' } },
        shimmer: { from: { backgroundPosition: '0% 50%' }, to: { backgroundPosition: '200% 50%' } },
        kernel: { '0%,100%': { transform: 'translateY(0) rotate(0deg)' }, '50%': { transform: 'translateY(-5px) rotate(18deg)' } },
      },
      animation: {
        rise: 'rise 0.45s cubic-bezier(0.2, 0.8, 0.2, 1) both',
        floaty: 'floaty 4s ease-in-out infinite',
        drift: 'drift 9s ease-in-out infinite',
        pop: 'pop 0.35s cubic-bezier(0.2, 0.8, 0.2, 1) both',
        blink: 'blink 5s ease-in-out infinite',
        shimmer: 'shimmer 3.5s linear infinite',
        kernel: 'kernel 2.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
