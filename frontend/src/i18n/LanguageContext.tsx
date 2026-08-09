import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { translations } from "./translations";

export type Lang = "zh-Hant" | "en";

const STORAGE_KEY = "agency_lang";
const DEFAULT_LANG: Lang = "zh-Hant";

function readStoredLang(): Lang {
  const v = typeof localStorage !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
  return v === "en" || v === "zh-Hant" ? v : DEFAULT_LANG;
}

// Module-level mirror of the active language so pure helpers (money, pct, enum
// label functions) can localize without threading `lang` through every call
// site. The provider keeps this in sync; components that render translated text
// consume the context and therefore re-render when it changes.
let activeLang: Lang = readStoredLang();

export function getActiveLang(): Lang {
  return activeLang;
}

export type TParams = Record<string, string | number>;

// Core lookup: resolve a key for the active language and interpolate {tokens}.
// Falls back to the other language, then to the raw key (so missing keys are
// visible during development rather than rendering blank).
export function translate(key: string, params?: TParams): string {
  const entry = translations[key];
  let text = entry ? (entry[activeLang] ?? entry.en ?? key) : key;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      text = text.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
    }
  }
  return text;
}

interface LanguageCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string, params?: TParams) => string;
}

const Ctx = createContext<LanguageCtx | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(activeLang);

  const setLang = (l: Lang) => {
    activeLang = l; // update the mirror before triggering re-render
    try { localStorage.setItem(STORAGE_KEY, l); } catch { /* ignore */ }
    setLangState(l);
  };

  useEffect(() => {
    document.documentElement.lang = lang;
    document.title = translate("app.title");
  }, [lang]);

  const value = useMemo<LanguageCtx>(
    () => ({ lang, setLang, t: (key, params) => translate(key, params) }),
    [lang],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): LanguageCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useI18n must be used within a LanguageProvider");
  return ctx;
}
