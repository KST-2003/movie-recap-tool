import React, { useEffect } from 'react';
import { Route, Routes, useLocation } from 'react-router-dom';
import { useLang } from './lang.jsx';
import Nav from './components/Nav.jsx';
import Footer from './components/Footer.jsx';
import Home from './pages/Home.jsx';
import About from './pages/About.jsx';
import Contact from './pages/Contact.jsx';
import Pricing from './pages/Pricing.jsx';
import Legal from './pages/Legal.jsx';
import NotFound from './pages/NotFound.jsx';

const TITLES = { '/': 'Make any video speak Burmese', '/about': 'About us', '/contact': 'Contact us', '/pricing': 'Pricing', '/privacy': 'Privacy Policy', '/terms': 'Terms of Use' };

// New page = back to the top; a link like /#features scrolls to that part. Also sets the tab title.
function PageEffects() {
  const { pathname, hash } = useLocation();
  useEffect(() => {
    document.title = `${pathname === '/' || !TITLES[pathname] ? 'Recat Studio' : `${TITLES[pathname]} · Recat Studio`}${pathname === '/' ? ' · ' + TITLES['/'] : ''}`;
    if (hash) {
      const go = () => document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      const t = setTimeout(go, 60);
      return () => clearTimeout(t);
    }
    window.scrollTo({ top: 0, behavior: 'instant' in window ? 'instant' : 'auto' });
    return undefined;
  }, [pathname, hash]);
  return null;
}

export default function App() {
  const { lang } = useLang();
  const { pathname } = useLocation();
  return (
    <div className="relative min-h-screen bg-page">
      <PageEffects />
      <Nav />
      <main key={pathname + lang} className="page-in">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/about" element={<About />} />
          <Route path="/contact" element={<Contact />} />
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/privacy" element={<Legal kind="privacy" />} />
          <Route path="/terms" element={<Legal kind="terms" />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <Footer />
    </div>
  );
}
