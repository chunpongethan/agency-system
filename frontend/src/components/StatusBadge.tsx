export default function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "settled" ? "settled" : status === "cancelled" ? "cancelled" : "pending";
  return <span className={`badge ${cls}`}>{status}</span>;
}
