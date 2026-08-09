import { useI18n } from "../i18n/LanguageContext";

// Small segmented control to switch between Traditional Chinese and English.
export default function LanguageToggle({ className }: { className?: string }) {
  const { lang, setLang, t } = useI18n();
  return (
    <div className={`seg ${className ?? ""}`}>
      <button className={lang === "zh-Hant" ? "active" : ""} onClick={() => setLang("zh-Hant")}>
        {t("lang.zh")}
      </button>
      <button className={lang === "en" ? "active" : ""} onClick={() => setLang("en")}>
        {t("lang.en")}
      </button>
    </div>
  );
}
