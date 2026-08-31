import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useI18n } from "../i18n/LanguageContext";
import ProductCatalogue from "../components/ProductCatalogue";

export default function Products() {
  const { t } = useI18n();
  const products = useQuery({ queryKey: ["products"], queryFn: () => api.products() });
  const [params] = useSearchParams();
  const focusId = params.get("focus") ? Number(params.get("focus")) : undefined;

  return (
    <div>
      <h1 className="page-title">{t("products.title")}</h1>
      <p className="page-sub">{t("products.subtitle")}</p>
      <div className="card">
        {products.isLoading && <div className="spinner">{t("common.loading")}</div>}
        {products.data && <ProductCatalogue products={products.data} focusId={focusId} />}
      </div>
    </div>
  );
}
