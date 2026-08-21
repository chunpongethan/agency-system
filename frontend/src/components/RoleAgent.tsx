/**
 * A Lead / SDR / Closing role cell: the agent's name and its split percentage,
 * or — when the role carries no share (0%). The code is kept as a hover title.
 */
export default function RoleAgent({ name, code, pct }:
  { name?: string | null; code?: string | null; pct?: string | number | null }) {
  const p = Number(pct ?? 0);
  if (!p) return <span className="muted">—</span>;
  return (
    <span title={code ?? undefined} style={{ whiteSpace: "nowrap" }}>
      {name ?? code ?? "—"}
      <span className="muted" style={{ fontSize: 11, marginLeft: 4 }}>{p}%</span>
    </span>
  );
}
