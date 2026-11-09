import React, { createContext, useContext, useMemo, useState } from 'react';
import { ADMIN_MY, ADMIN_SERVER } from './strings.js';

// Interface language of the admin app: 'my' (Myanmar) or 'en'. English text is the key (see strings.js); {name} placeholders
// are filled by tr(text, { name: value }). trs() translates texts that came from the server (exact match, then patterns).
export function makeTr(lang) {
  const fill = (s, vars) => (vars ? s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m)) : s);
  const tr = (s, vars) => fill(lang === 'my' ? (ADMIN_MY[s] ?? s) : s, vars);
  const trs = (s) => {
    if (!s || lang !== 'my') return s;
    if (ADMIN_MY[s]) return ADMIN_MY[s];
    for (const [re, out] of ADMIN_SERVER) {
      const m = s.match(re);
      if (m) return out.replace(/\$(\d)/g, (x, i) => m[Number(i)] ?? '');
    }
    return s;
  };
  return { tr, trs };
}

export const LangContext = createContext({ lang: 'en', setLang: () => {}, tr: (s) => s, trs: (s) => s });
export const useI18n = () => useContext(LangContext);

const initialLang = () => {
  try {
    const saved = localStorage.getItem('admin_lang');
    if (saved === 'my' || saved === 'en') return saved;
  } catch (e) { /* storage blocked */ }
  return (typeof navigator !== 'undefined' && /^(my|mya|bur)/i.test(navigator.language || '')) ? 'my' : 'en';
};

export function LangProvider({ children }) {
  const [lang, setLangState] = useState(initialLang);
  const setLang = (l) => {
    setLangState(l);
    try { localStorage.setItem('admin_lang', l); } catch (e) { /* ignore */ }
  };
  const value = useMemo(() => ({ lang, setLang, ...makeTr(lang) }), [lang]);
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export function LangSwitch() {
  const { lang, setLang } = useI18n();
  return (
    <span className="inline-flex overflow-hidden rounded-lg border border-slate-700 text-xs">
      {[['my', 'မြန်မာ'], ['en', 'English']].map(([k, label]) => (
        <button key={k} type="button" onClick={() => setLang(k)}
          className={`px-2.5 py-1 ${lang === k ? 'bg-purple-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'}`}>{label}</button>
      ))}
    </span>
  );
}
