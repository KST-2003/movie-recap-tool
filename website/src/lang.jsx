import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { C } from './content.js';

const Ctx = createContext({ lang: 'en', setLang: () => {}, c: C.en });

const read = () => {
  const q = new URLSearchParams(window.location.search).get('lang');   // a shared link like /?lang=my
  if (q === 'en' || q === 'my') return q;
  try {
    const saved = localStorage.getItem('recat_site_lang');
    if (saved === 'en' || saved === 'my') return saved;
  } catch { /* private window: fine */ }
  return (navigator.language || '').toLowerCase().startsWith('my') ? 'my' : 'en';
};

export function LangProvider({ children }) {
  const [lang, setLangState] = useState(read);
  const setLang = (l) => { setLangState(l); try { localStorage.setItem('recat_site_lang', l); } catch { /* ignore */ } };
  useEffect(() => { document.documentElement.lang = lang === 'my' ? 'my' : 'en'; }, [lang]);
  const value = useMemo(() => ({ lang, setLang, c: C[lang] }), [lang]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useLang = () => useContext(Ctx);
