import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useState } from "react";
import { useI18n } from "../i18n/LanguageContext";

interface Props<T> {
  data: T[];
  columns: ColumnDef<T, any>[];
  empty?: string;
  // On mobile, render each row as a stacked card (labels from column headers).
  cardsOnMobile?: boolean;
}

// A small sortable grid built on TanStack Table, used for ledger/summary grids.
export default function DataTable<T>({ data, columns, empty, cardsOnMobile }: Props<T>) {
  const { t } = useI18n();
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
    <div className="table-scroll">
    <table className={cardsOnMobile ? "cards-on-mobile" : ""}>
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
            {row.getVisibleCells().map((cell) => {
              const header = cell.column.columnDef.header;
              return (
                <td
                  key={cell.id}
                  data-label={typeof header === "string" ? header : undefined}
                  className={(cell.column.columnDef.meta as { num?: boolean })?.num ? "num" : ""}
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              );
            })}
          </tr>
        ))}
        {data.length === 0 && (
          <tr>
            <td colSpan={columns.length} className="muted">
              {empty ?? t("common.noRows")}
            </td>
          </tr>
        )}
      </tbody>
    </table>
    </div>
  );
}
