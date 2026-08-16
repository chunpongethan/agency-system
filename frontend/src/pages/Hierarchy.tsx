import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useI18n } from "../i18n/LanguageContext";
import { money } from "../lib/format";
import { titleLabel } from "../lib/titles";
import { roleLabel } from "../i18n/labels";
import TargetProgress from "../components/TargetProgress";
import type { Agent, TeamProductionRow, PeriodProduction } from "../api/types";

const ZERO: PeriodProduction = { afyp: 0, commission: 0, override: 0 };

interface TreeNode extends Agent {
  children: TreeNode[];
  own: TeamProductionRow;      // this agent's own production (3 periods)
  teamAfyp: number;            // rolled-up YTD AFYP over the subtree
  teamComm: number;            // rolled-up YTD direct commission over the subtree
  teamOverride: number;        // rolled-up YTD override over the subtree
}

function buildTree(agents: Agent[], prod: Map<number, TeamProductionRow>): TreeNode[] {
  const nodes = new Map<number, TreeNode>();
  agents.forEach((a) =>
    nodes.set(a.id, {
      ...a, children: [],
      own: prod.get(a.id) ?? { agent_id: a.id, ytd: ZERO, last_month: ZERO, current_month: ZERO },
      teamAfyp: 0, teamComm: 0, teamOverride: 0,
    }),
  );
  const roots: TreeNode[] = [];
  nodes.forEach((n) => {
    if (n.upline_id != null && nodes.has(n.upline_id)) nodes.get(n.upline_id)!.children.push(n);
    else roots.push(n);
  });
  const rollup = (n: TreeNode) => {
    n.teamAfyp = n.own.ytd.afyp;
    n.teamComm = n.own.ytd.commission;
    n.teamOverride = n.own.ytd.override;
    n.children.forEach((c) => {
      rollup(c);
      n.teamAfyp += c.teamAfyp; n.teamComm += c.teamComm; n.teamOverride += c.teamOverride;
    });
  };
  roots.forEach(rollup);
  return roots;
}

function flatten(n: TreeNode, out: TreeNode[] = []): TreeNode[] {
  out.push(n);
  n.children.forEach((c) => flatten(c, out));
  return out;
}

function NodeRow({
  node, collapsed, toggle, selectedId, onSelect, targetByTitle,
}: {
  node: TreeNode; collapsed: Set<number>; toggle: (id: number) => void;
  selectedId: number | null; onSelect: (id: number) => void;
  targetByTitle: Map<string, number>;
}) {
  const { t } = useI18n();
  const hasChildren = node.children.length > 0;
  const isCollapsed = collapsed.has(node.id);
  const isManager = node.role === "manager";
  const nodeTarget = node.title ? (targetByTitle.get(node.title) ?? 0) : 0;
  // Managers are scored on their whole team's YTD AFYP; agents on their own.
  const nodeAchievedAfyp = isManager ? node.teamAfyp : node.own.ytd.afyp;
  return (
    <li>
      <div className="node">
        {hasChildren ? (
          <button className="caret" aria-label={isCollapsed ? "expand" : "collapse"}
            onClick={() => toggle(node.id)}>{isCollapsed ? "▸" : "▾"}</button>
        ) : <span className="caret spacer" />}
        <button className={`node-main ${selectedId === node.id ? "selected" : ""}`}
          onClick={() => onSelect(node.id)}>
          <span className="lvl">L{node.level}</span>
          <strong>{node.name}</strong>
          <span className="muted">({node.code})</span>
          <span className="badge role">{roleLabel(node.role)}</span>
          {node.title && <span className="badge title">{titleLabel(node.title)}</span>}
          {isManager && node.unit_code && <span className="badge unit">{node.unit_code}</span>}
          {node.direct_client && <span className="badge dc">{t("admin.agents.thDirectClient")}</span>}
          <span className="node-metric">
            <span className="metric-label">{t("hierarchy.teamAfyp")}</span> {money(node.teamAfyp)}
          </span>
          <span className="node-metric">
            <span className="metric-label">{t("hierarchy.teamComm")}</span> {money(node.teamComm)}
          </span>
          <span className="node-metric">
            <span className="metric-label">{t("hierarchy.teamOverride")}</span> {money(node.teamOverride)}
          </span>
          {nodeTarget > 0 && (
            <span className="node-metric" onClick={(e) => e.stopPropagation()}>
              <span className="metric-label">{t("hierarchy.targetProgress")}</span>
              <TargetProgress afypUsd={nodeAchievedAfyp} targetHkd={nodeTarget} width={80} />
            </span>
          )}
        </button>
      </div>
      {hasChildren && !isCollapsed && (
        <ul>
          {node.children.map((c) => (
            <NodeRow key={c.id} node={c} collapsed={collapsed} toggle={toggle}
              selectedId={selectedId} onSelect={onSelect} targetByTitle={targetByTitle} />
          ))}
        </ul>
      )}
    </li>
  );
}

function TeamPanel({ node, onClose }: { node: TreeNode; onClose: () => void }) {
  const { t } = useI18n();
  const members = flatten(node);
  const totals = members.reduce(
    (t, m) => ({
      ya: t.ya + m.own.ytd.afyp, yc: t.yc + m.own.ytd.commission,
      la: t.la + m.own.last_month.afyp, lc: t.lc + m.own.last_month.commission,
      ca: t.ca + m.own.current_month.afyp, cc: t.cc + m.own.current_month.commission,
    }),
    { ya: 0, yc: 0, la: 0, lc: 0, ca: 0, cc: 0 },
  );
  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h2>
          {node.role === "manager" ? t("hierarchy.teamProduction") : t("hierarchy.production")} — {node.name}
          {node.unit_code ? ` · ${node.unit_code}` : ""}
        </h2>
        <button className="ghost" onClick={onClose} style={{ padding: "2px 8px" }}>✕</button>
      </div>
      <p className="muted" style={{ fontSize: 12, marginTop: -6 }}>
        {t("hierarchy.membersNote", { count: members.length })}
      </p>
      <div style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              <th rowSpan={2}>{t("hierarchy.member")}</th>
              <th colSpan={2} style={{ textAlign: "center" }}>{t("common.ytd")}</th>
              <th colSpan={2} style={{ textAlign: "center" }}>{t("common.lastMonth")}</th>
              <th colSpan={2} style={{ textAlign: "center" }}>{t("common.currentMonth")}</th>
            </tr>
            <tr>
              <th className="num">{t("common.afyp")}</th><th className="num">{t("scorecard.comm")}</th>
              <th className="num">{t("common.afyp")}</th><th className="num">{t("scorecard.comm")}</th>
              <th className="num">{t("common.afyp")}</th><th className="num">{t("scorecard.comm")}</th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.id}>
                <td>
                  <span className="lvl">L{m.level}</span> {m.name}{" "}
                  <span className="muted">({m.code})</span>
                  {m.role === "manager" && <span className="badge role" style={{ marginLeft: 6 }}>{t("hierarchy.mgr")}</span>}
                </td>
                <td className="num">{money(m.own.ytd.afyp)}</td>
                <td className="num">{money(m.own.ytd.commission)}</td>
                <td className="num">{money(m.own.last_month.afyp)}</td>
                <td className="num">{money(m.own.last_month.commission)}</td>
                <td className="num">{money(m.own.current_month.afyp)}</td>
                <td className="num">{money(m.own.current_month.commission)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr style={{ fontWeight: 700 }}>
              <td>{t("hierarchy.teamTotal")}</td>
              <td className="num">{money(totals.ya)}</td><td className="num">{money(totals.yc)}</td>
              <td className="num">{money(totals.la)}</td><td className="num">{money(totals.lc)}</td>
              <td className="num">{money(totals.ca)}</td><td className="num">{money(totals.cc)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

export default function Hierarchy() {
  const { t } = useI18n();
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => api.agents() });
  const production = useQuery({ queryKey: ["teamProduction"], queryFn: () => api.teamProduction() });
  const titleTargets = useQuery({ queryKey: ["titleTargets"], queryFn: () => api.titleTargets() });
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const [selectedId, setSelectedId] = useState<number | null>(null);

  if (agents.isLoading || production.isLoading) return <div className="spinner">{t("common.loading")}</div>;

  const targetByTitle = new Map((titleTargets.data ?? []).map((tt) => [tt.title, tt.target_afyp]));

  const prodMap = new Map<number, TeamProductionRow>(
    (production.data ?? []).map((r) => [r.agent_id, r]),
  );
  // Admins are not part of the selling hierarchy; terminated agents are hidden.
  const sellingAgents = (agents.data ?? []).filter((a) => a.role !== "admin" && a.is_active);
  const roots = buildTree(sellingAgents, prodMap);
  const allNodes = roots.flatMap((r) => flatten(r));
  const selected = selectedId != null ? allNodes.find((n) => n.id === selectedId) : undefined;

  const toggle = (id: number) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  const collapseAll = () => {
    const all = new Set<number>();
    sellingAgents.forEach((a) => {
      if (sellingAgents.some((c) => c.upline_id === a.id)) all.add(a.id);
    });
    setCollapsed(all);
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1 className="page-title">{t("hierarchy.title")}</h1>
          <p className="page-sub">{t("hierarchy.subtitle")}</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="ghost" onClick={() => setCollapsed(new Set())}>{t("hierarchy.expandAll")}</button>
          <button className="ghost" onClick={collapseAll}>{t("hierarchy.collapseAll")}</button>
        </div>
      </div>

      <div className="card tree">
        <ul>
          {roots.map((r) => (
            <NodeRow key={r.id} node={r} collapsed={collapsed} toggle={toggle}
              selectedId={selectedId} onSelect={setSelectedId} targetByTitle={targetByTitle} />
          ))}
        </ul>
      </div>

      {selected && <TeamPanel node={selected} onClose={() => setSelectedId(null)} />}
    </div>
  );
}
