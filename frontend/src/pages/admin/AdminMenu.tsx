import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../../api/client";
import { useI18n } from "../../i18n/LanguageContext";
import { MENU, type MenuItem } from "../../lib/menu";
import type { MenuSetting } from "../../api/types";

type Row = { key: string; enabled: boolean; label: string };
type Groups = { main: Row[]; admin: Row[] };

function initialGroups(settings: MenuSetting[]): Groups {
  const byKey = new Map(settings.map((s) => [s.key, s]));
  const idx = (m: MenuItem) => MENU.indexOf(m);
  const ord = (m: MenuItem) => byKey.get(m.key)?.sort_order ?? idx(m);
  const all = [...MENU].sort((a, b) => ord(a) - ord(b) || idx(a) - idx(b));
  const toRow = (m: MenuItem): Row => ({
    key: m.key,
    enabled: m.locked ? true : (byKey.get(m.key)?.enabled ?? true),
    label: byKey.get(m.key)?.label ?? "",
  });
  return {
    main: all.filter((m) => m.group === "main").map(toRow),
    admin: all.filter((m) => m.group === "admin").map(toRow),
  };
}

export default function AdminMenu() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["menuSettings"], queryFn: () => api.menuSettings() });
  const byKey = useMemo(() => new Map(MENU.map((m) => [m.key, m])), []);

  const [groups, setGroups] = useState<Groups | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (settings.data) setGroups(initialGroups(settings.data)); }, [settings.data]);

  const save = useMutation({
    mutationFn: () => {
      const flat: MenuSetting[] = [];
      let order = 0;
      for (const g of [groups!.main, groups!.admin]) {
        for (const r of g) flat.push({ key: r.key, enabled: r.enabled, sort_order: order++, label: r.label.trim() || null });
      }
      return api.saveMenuSettings(flat);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["menuSettings"] }); setError(null); },
    onError: (e) => setError(errorText(e, t)),
  });

  if (!groups) return <div className="spinner">{t("common.loading")}</div>;

  function toggle(group: "main" | "admin", i: number) {
    setGroups((g) => {
      if (!g) return g;
      const rows = g[group].map((r, j) => (j === i ? { ...r, enabled: !r.enabled } : r));
      return { ...g, [group]: rows };
    });
  }
  function setLabel(group: "main" | "admin", i: number, value: string) {
    setGroups((g) => {
      if (!g) return g;
      const rows = g[group].map((r, j) => (j === i ? { ...r, label: value } : r));
      return { ...g, [group]: rows };
    });
  }
  function move(group: "main" | "admin", i: number, dir: -1 | 1) {
    setGroups((g) => {
      if (!g) return g;
      const rows = [...g[group]];
      const j = i + dir;
      if (j < 0 || j >= rows.length) return g;
      [rows[i], rows[j]] = [rows[j], rows[i]];
      return { ...g, [group]: rows };
    });
  }
  function resetDefaults() { setGroups(initialGroups([])); }

  const Section = ({ group, title }: { group: "main" | "admin"; title: string }) => (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>{title}</h2>
      <div className="menu-editor">
        {groups[group].map((r, i) => {
          const item = byKey.get(r.key)!;
          return (
            <div key={r.key} className={`menu-row ${r.enabled ? "" : "off"}`}>
              <div className="menu-reorder">
                <button className="ghost" disabled={i === 0} onClick={() => move(group, i, -1)} title="↑">↑</button>
                <button className="ghost" disabled={i === groups[group].length - 1} onClick={() => move(group, i, 1)} title="↓">↓</button>
              </div>
              <input className="menu-name" value={r.label} placeholder={t(item.labelKey)}
                onChange={(e) => setLabel(group, i, e.target.value)} />
              <code className="muted menu-path">{item.to}</code>
              <label className="menu-toggle">
                <input type="checkbox" style={{ width: "auto" }} checked={r.enabled}
                  disabled={item.locked} onChange={() => toggle(group, i)} />
                {t("menu.visible")}
              </label>
            </div>
          );
        })}
      </div>
    </div>
  );

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 className="page-title">{t("menu.title")}</h1>
          <p className="page-sub">{t("menu.subtitle")}</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="ghost" onClick={resetDefaults}>{t("menu.reset")}</button>
          <button className="primary" onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? t("common.saving") : t("common.save")}
          </button>
        </div>
      </div>
      {error && <div className="error" style={{ marginTop: 10 }}>{error}</div>}
      <p className="muted" style={{ fontSize: 13 }}>{t("menu.hint")}</p>

      <Section group="main" title={t("menu.mainGroup")} />
      <Section group="admin" title={t("menu.adminGroup")} />
    </div>
  );
}
