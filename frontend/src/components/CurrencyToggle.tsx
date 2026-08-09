import { useI18n } from "../i18n/LanguageContext";
import type { Currency } from "../i18n/LanguageContext";

const CURRENCIES: Currency[] = ["USD", "HKD"];

// System-wide display-currency switch (USD / HKD). All money figures convert to
// the chosen currency using fixed demo FX rates.
export default function CurrencyToggle({ className }: { className?: string }) {
  const { currency, setCurrency } = useI18n();
  return (
    <div className={`seg ${className ?? ""}`}>
      {CURRENCIES.map((c) => (
        <button key={c} className={currency === c ? "active" : ""} onClick={() => setCurrency(c)}>
          {c}
        </button>
      ))}
    </div>
  );
}
