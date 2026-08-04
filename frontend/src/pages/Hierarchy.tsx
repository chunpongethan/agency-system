import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { money } from "../lib/format";
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

function NodeView({ node }: { node: TreeNode }) {
  return (
    <li>
      <div className="node">
        <span className="lvl">L{node.level}</span>
        <strong>{node.name}</strong>
        <span className="muted">({node.code})</span>
        <span className="badge role">{node.role}</span>
        <span className="prod">{money(node.rolled)}</span>
        {node.children.length > 0 && (
          <span className="muted" style={{ fontSize: 12 }}>
            own {money(node.own)}
          </span>
        )}
      </div>
      {node.children.length > 0 && (
        <ul>
          {node.children.map((c) => (
            <NodeView key={c.id} node={c} />
          ))}
        </ul>
      )}
    </li>
  );
}

export default function Hierarchy() {
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => api.agents() });
  const summary = useQuery({ queryKey: ["agencySummary"], queryFn: () => api.agencySummary() });

  if (agents.isLoading || summary.isLoading)
    return <div className="spinner">Loading…</div>;

  const totals = new Map<number, number>(
    (summary.data ?? []).map((r) => [r.agent_id, r.total]),
  );
  const roots = buildTree(agents.data ?? [], totals);

  return (
    <div>
      <h1 className="page-title">Hierarchy</h1>
      <p className="page-sub">Org tree with rolled-up production per node</p>
      <div className="card tree">
        <ul>
          {roots.map((r) => (
            <NodeView key={r.id} node={r} />
          ))}
        </ul>
      </div>
    </div>
  );
}
