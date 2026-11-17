/** @type {import('tailwindcss').Config} */
// Same Recat tokens as the user app (frontend/tailwind.config.js): primary violet-500 #8B5CF6, lavender, blush, popcorn, page #F7F4FF.
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
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
        display: ['Fredoka', 'Poppins', '"Noto Sans Myanmar"', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        card: '0 10px 30px -12px rgba(139, 92, 246, 0.25)',
        pop: '0 8px 20px -6px rgba(139, 92, 246, 0.55)',
        lift: '0 24px 50px -18px rgba(139, 92, 246, 0.45)',
      },
      keyframes: {
        floaty: { '0%,100%': { transform: 'translateY(0) rotate(-2deg)' }, '50%': { transform: 'translateY(-12px) rotate(2deg)' } },
        drift: { '0%,100%': { transform: 'translate(0,0)' }, '50%': { transform: 'translate(24px,-16px)' } },
        pop: { '0%': { transform: 'scale(0.6)', opacity: 0 }, '60%': { transform: 'scale(1.12)', opacity: 1 }, '100%': { transform: 'scale(1)', opacity: 1 } },
        shimmer: { from: { backgroundPosition: '0% 50%' }, to: { backgroundPosition: '200% 50%' } },
        kernel: { '0%,100%': { transform: 'translateY(0) rotate(0deg)' }, '50%': { transform: 'translateY(-10px) rotate(24deg)' } },
        marquee: { from: { transform: 'translateX(0)' }, to: { transform: 'translateX(-50%)' } },
        bar: { '0%,100%': { transform: 'scaleY(0.25)' }, '50%': { transform: 'scaleY(1)' } },
        heart: { '0%': { transform: 'translateY(0) scale(0.6)', opacity: 0 }, '20%': { opacity: 1 }, '100%': { transform: 'translateY(-70px) scale(1.1)', opacity: 0 } },
        sweep: { from: { transform: 'translateX(-120%)' }, to: { transform: 'translateX(220%)' } },
        wiggle: { '0%,100%': { transform: 'rotate(-4deg)' }, '50%': { transform: 'rotate(4deg)' } },
        blink: { '0%,100%': { opacity: 1 }, '50%': { opacity: 0 } },
      },
      animation: {
        floaty: 'floaty 5s ease-in-out infinite',
        drift: 'drift 12s ease-in-out infinite',
        pop: 'pop 0.4s cubic-bezier(0.2, 0.8, 0.2, 1) both',
        shimmer: 'shimmer 3.5s linear infinite',
        kernel: 'kernel 3s ease-in-out infinite',
        marquee: 'marquee 28s linear infinite',
        bar: 'bar 1s ease-in-out infinite',
        heart: 'heart 3.2s ease-out infinite',
        sweep: 'sweep 3.4s ease-in-out infinite',
        wiggle: 'wiggle 2.4s ease-in-out infinite',
        blink: 'blink 1s steps(2) infinite',
      },
    },
  },
  plugins: [],
}
