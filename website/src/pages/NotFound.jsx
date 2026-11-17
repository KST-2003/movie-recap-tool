import React from 'react';
import { ArrowRight } from 'lucide-react';
import { useLang } from '../lang.jsx';
import { Blobs, Btn, Kernel } from '../components/Bits.jsx';

export default function NotFound() {
  const { c } = useLang();
  return (
    <section className="relative flex min-h-[80vh] items-center justify-center overflow-hidden px-4 pt-28 text-center">
      <Blobs />
      <div className="page-in relative">
        <div className="relative mx-auto w-56">
          <img src="/recat-maintenance.webp" alt="" className="animate-floaty drop-shadow-xl" width="224" height="205" />
          <Kernel size={30} className="absolute -left-4 top-4 animate-kernel" />
        </div>
        <div className="text-candy animate-shimmer mt-4 font-display text-7xl font-semibold">404</div>
        <h1 className="mt-2 font-display text-2xl font-semibold sm:text-3xl">{c.notFound.title}</h1>
        <p className="mx-auto mt-2 max-w-md text-ink-soft">{c.notFound.sub}</p>
        <Btn to="/" className="mt-6">{c.notFound.btn}<ArrowRight size={16} /></Btn>
      </div>
    </section>
  );
}
