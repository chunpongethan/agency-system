/**
 * A Lead / SDR / Closing role cell: the agent's code and its split percentage,
 * or — when the role carries no share (0%). Names come resolved from the server.
 */
export default function RoleAgent({ code, pct }:
  { code?: string | null; pct?: string | number | null }) {
  const p = Number(pct ?? 0);
  if (!p) return <span className="muted">—</span>;
  return (
    <span style={{ whiteSpace: "nowrap" }}>
      {code ?? "—"}
      <span className="muted" style={{ fontSize: 11, marginLeft: 4 }}>{p}%</span>
    </span>
  );
}
