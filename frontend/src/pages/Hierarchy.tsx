import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { money, currentPeriod } from "../lib/format";
import { titleLabel } from "../lib/titles";
import StatusBadge from "../components/StatusBadge";
import type { Agent } from "../api/types";

interface TreeNode extends Agent {
  children: TreeNode[];
  own: number;
  rolled: number;
}

function buildTree(agents: Agent[], totals: Map<number, number>): TreeNode[] {
  const nodes = new Map<number, TreeNode>();
  agents.forEach((a) =>
    nodes.set(a.id, { ...a, children: [], own: totals.get(a.id) ?? 0, rolled: 0 }),
  );
  const roots: TreeNode[] = [];
  nodes.forEach((n) => {
    if (n.upline_id != null && nodes.has(n.upline_id)) {
      nodes.get(n.upline_id)!.children.push(n);
    } else {
      roots.push(n);
    }
  });
  const rollup = (n: TreeNode): number => {
    n.rolled = n.own + n.children.reduce((s, c) => s + rollup(c), 0);
    return n.rolled;
  };
  roots.forEach(rollup);
  return roots;
}

function countSubtree(n: TreeNode): number {
  return n.children.reduce((s, c) => s + 1 + countSubtree(c), 0);
}

function NodeRow({
  node, collapsed, toggle, selectedId, onSelect,
}: {
  node: TreeNode;
  collapsed: Set<number>;
  toggle: (id: number) => void;
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  const hasChildren = node.children.length > 0;
  const isCollapsed = collapsed.has(node.id);
  return (
    <li>
      <div className="node">
        {hasChildren ? (
          <button
            className="caret"
            aria-label={isCollapsed ? "expand" : "collapse"}
            onClick={() => toggle(node.id)}
          >
            {isCollapsed ? "▸" : "▾"}
          </button>
        ) : (
          <span className="caret spacer" />
        )}
        <button
          className={`node-main ${selectedId === node.id ? "selected" : ""}`}
          onClick={() => onSelect(node.id)}
        >
          <span className="lvl">L{node.level}</span>
          <strong>{node.name}</strong>
          <span className="muted">({node.code})</span>
          <span className="badge role">{node.role}</span>
          {node.title && <span className="badge title">{titleLabel(node.title)}</span>}
          <span className="prod">{money(node.rolled)}</span>
          <span className="node-meta muted">
            {hasChildren
              ? `${node.children.length} direct · ${countSubtree(node)} total · own ${money(node.own)}`
              : "frontline"}
          </span>
        </button>
      </div>
      {hasChildren && !isCollapsed && (
        <ul>
          {node.children.map((c) => (
            <NodeRow
              key={c.id}
              node={c}
              collapsed={collapsed}
              toggle={toggle}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

function DetailPanel({
  agentId, agents, onClose,
}: {
  agentId: number;
  agents: Agent[];
  onClose: () => void;
}) {
  const period = currentPeriod();
  const agent = agents.find((a) => a.id === agentId);
  const upline = agents.find((a) => a.id === agent?.upline_id);
  const statement = useQuery({
    queryKey: ["h-statement", agentId, period.ym],
    queryFn: () => api.agentStatement(agentId, period.start, period.end),
  });
  const clients = useQuery({
    queryKey: ["h-clients", agentId],
    queryFn: () => api.agentClients(agentId),
  });
  const txns = useQuery({
    queryKey: ["h-txns", agentId],
    queryFn: () => api.agentTransactions(agentId),
  });

  if (!agent) return null;

  return (
    <div className="card detail-panel">
      <div className="detail-head">
        <div>
          <div style={{ fontSize: 16, fontWeight: 700 }}>{agent.name}</div>
          <div className="muted" style={{ fontSize: 12 }}>
            {agent.code} · depth L{agent.level}
            {upline ? ` · reports to ${upline.name}` : " · top of line"}
          </div>
          <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
            <span className="badge role">{agent.role}</span>
            {agent.title && <span className="badge title">{titleLabel(agent.title)}</span>}
          </div>
        </div>
        <button className="ghost" onClick={onClose} aria-label="close" style={{ padding: "2px 8px" }}>✕</button>
      </div>

      <h2 style={{ marginTop: 16 }}>This period ({period.ym})</h2>
      {statement.isLoading ? (
        <div className="spinner">Loading…</div>
      ) : (
        <div className="detail-stats">
          <div className="stat">
            <div className="label">Direct</div>
            <div className="value good">{money(statement.data?.direct_total ?? 0)}</div>
          </div>
          <div className="stat">
            <div className="label">Override</div>
            <div className="value good">{money(statement.data?.override_total ?? 0)}</div>
          </div>
          <div className="stat">
            <div className="label">Total</div>
            <div className="value">{money(statement.data?.grand_total ?? 0)}</div>
          </div>
        </div>
      )}

      <h2 style={{ marginTop: 16 }}>Clients{clients.data ? ` (${clients.data.length})` : ""}</h2>
      {clients.isError ? (
        <p className="muted" style={{ fontSize: 12 }}>
          🔒 Client details are private to {agent.name}. Only the owning agent can view them.
        </p>
      ) : (
        <table>
          <tbody>
            {clients.data?.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td className="muted">{c.ref}</td>
                <td className="muted">{c.risk_profile ?? "—"}</td>
              </tr>
            ))}
            {clients.data?.length === 0 && (
              <tr><td className="muted">No own clients (overrides come from downline).</td></tr>
            )}
          </tbody>
        </table>
      )}

      <h2 style={{ marginTop: 16 }}>Recent transactions</h2>
      {txns.isError ? (
        <p className="muted" style={{ fontSize: 12 }}>
          🔒 Transactions are private to {agent.name}.
        </p>
      ) : (
        <table>
          <tbody>
            {txns.data?.slice(0, 6).map((t) => (
              <tr key={t.id}>
                <td>{t.ref}</td>
                <td className="muted">{t.trade_date}</td>
                <td className="num">{money(t.notional, t.currency)}</td>
                <td><StatusBadge status={t.status} /></td>
              </tr>
            ))}
            {txns.data?.length === 0 && (
              <tr><td className="muted">No transactions closed by this agent.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function Hierarchy() {
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => api.agents() });
  const summary = useQuery({ queryKey: ["agencySummary"], queryFn: () => api.agencySummary() });
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const [selectedId, setSelectedId] = useState<number | null>(null);

  if (agents.isLoading || summary.isLoading)
    return <div className="spinner">Loading…</div>;

  const totals = new Map<number, number>(
    (summary.data ?? []).map((r) => [r.agent_id, r.total]),
  );
  // Admins are not part of the selling hierarchy — exclude them from the tree.
  const sellingAgents = (agents.data ?? []).filter((a) => a.role !== "admin");
  const roots = buildTree(sellingAgents, totals);

  const toggle = (id: number) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const collapseAll = () => {
    const all = new Set<number>();
    (agents.data ?? []).forEach((a) => {
      if ((agents.data ?? []).some((c) => c.upline_id === a.id)) all.add(a.id);
    });
    setCollapsed(all);
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1 className="page-title">Hierarchy</h1>
          <p className="page-sub">
            Org tree with rolled-up production. Click an agent to drill in; use the ▸/▾ carets to fold branches.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="ghost" onClick={() => setCollapsed(new Set())}>Expand all</button>
          <button className="ghost" onClick={collapseAll}>Collapse all</button>
        </div>
      </div>

      <div className="hierarchy-layout">
        <div className="card tree">
          <ul>
            {roots.map((r) => (
              <NodeRow
                key={r.id}
                node={r}
                collapsed={collapsed}
                toggle={toggle}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            ))}
          </ul>
        </div>
        {selectedId != null && (
          <DetailPanel
            agentId={selectedId}
            agents={agents.data ?? []}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>
    </div>
  );
}
