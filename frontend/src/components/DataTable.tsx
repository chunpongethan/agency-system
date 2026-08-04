import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useState } from "react";

interface Props<T> {
  data: T[];
  columns: ColumnDef<T, any>[];
  empty?: string;
}

// A small sortable grid built on TanStack Table, used for ledger/summary grids.
export default function DataTable<T>({ data, columns, empty }: Props<T>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <table>
      <thead>
        {table.getHeaderGroups().map((hg) => (
          <tr key={hg.id}>
            {hg.headers.map((h) => (
              <th
                key={h.id}
                className={(h.column.columnDef.meta as { num?: boolean })?.num ? "num" : ""}
                style={{ cursor: h.column.getCanSort() ? "pointer" : "default" }}
                onClick={h.column.getToggleSortingHandler()}
              >
                {flexRender(h.column.columnDef.header, h.getContext())}
                {{ asc: " ▲", desc: " ▼" }[h.column.getIsSorted() as string] ?? ""}
              </th>
            ))}
          </tr>
        ))}
      </thead>
      <tbody>
        {table.getRowModel().rows.map((row) => (
          <tr key={row.id}>
            {row.getVisibleCells().map((cell) => (
              <td
                key={cell.id}
                className={(cell.column.columnDef.meta as { num?: boolean })?.num ? "num" : ""}
              >
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </td>
            ))}
          </tr>
        ))}
        {data.length === 0 && (
          <tr>
            <td colSpan={columns.length} className="muted">
              {empty ?? "No rows."}
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
