import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { translations } from "./translations";

export type Lang = "zh-Hant" | "en";
export type Currency = "USD" | "HKD";

const STORAGE_KEY = "agency_lang";
const CURRENCY_KEY = "agency_currency";
const DEFAULT_LANG: Lang = "zh-Hant";
const DEFAULT_CURRENCY: Currency = "HKD";

function readStoredLang(): Lang {
  const v = typeof localStorage !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
  return v === "en" || v === "zh-Hant" ? v : DEFAULT_LANG;
}

function readStoredCurrency(): Currency {
  const v = typeof localStorage !== "undefined" ? localStorage.getItem(CURRENCY_KEY) : null;
  return v === "USD" || v === "HKD" ? v : DEFAULT_CURRENCY;
}

// Module-level mirrors of the active language and display currency so pure
// helpers (money, pct, enum label functions) can read them without threading
// through every call site. The provider keeps these in sync; components that
// render preference-dependent text consume the context and re-render on change.
let activeLang: Lang = readStoredLang();
let activeCurrency: Currency = readStoredCurrency();

export function getActiveLang(): Lang {
  return activeLang;
}

export function getActiveCurrency(): Currency {
  return activeCurrency;
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
  currency: Currency;
  setCurrency: (c: Currency) => void;
  t: (key: string, params?: TParams) => string;
}

const Ctx = createContext<LanguageCtx | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(activeLang);
  const [currency, setCurrencyState] = useState<Currency>(activeCurrency);

  const setLang = (l: Lang) => {
    activeLang = l; // update the mirror before triggering re-render
    try { localStorage.setItem(STORAGE_KEY, l); } catch { /* ignore */ }
    setLangState(l);
  };

  const setCurrency = (c: Currency) => {
    activeCurrency = c;
    try { localStorage.setItem(CURRENCY_KEY, c); } catch { /* ignore */ }
    setCurrencyState(c);
  };

  useEffect(() => {
    document.documentElement.lang = lang;
    document.title = translate("app.title");
  }, [lang]);

  const value = useMemo<LanguageCtx>(
    () => ({ lang, setLang, currency, setCurrency, t: (key, params) => translate(key, params) }),
    [lang, currency],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): LanguageCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useI18n must be used within a LanguageProvider");
  return ctx;
}
