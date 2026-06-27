import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface DataColumn<T> {
  key: string;
  header: string;
  className?: string;
  cellClassName?: string;
  render: (item: T) => ReactNode;
}

interface DataTableProps<T> {
  columns: DataColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  scrollClassName?: string;
  stickyHeader?: boolean;
  rowClassName?: string | ((row: T) => string);
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  scrollClassName,
  stickyHeader = false,
  rowClassName,
}: DataTableProps<T>) {
  return (
    <div className="overflow-hidden rounded-2xl border border-[var(--line)] bg-white shadow-[var(--shadow-card)]">
      <div className={cn("overflow-x-auto", scrollClassName)}>
        <table className="min-w-full border-separate border-spacing-0">
          <thead>
            <tr className="bg-[var(--panel)]">
              {columns.map((column) => (
                <th
                  key={column.key}
                  className={cn(
                    "border-b border-[var(--line)] px-4 py-3 text-left font-mono text-[11px] uppercase tracking-[0.24em] text-[var(--muted)]",
                    stickyHeader && "sticky top-0 z-10 bg-[var(--panel)]",
                    column.className,
                  )}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={rowKey(row)}
                className={cn(
                  "group",
                  typeof rowClassName === "function"
                    ? rowClassName(row)
                    : rowClassName,
                )}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn(
                      "border-b border-[var(--line)] px-4 py-4 align-top text-sm text-[var(--ink)] group-last:border-b-0",
                      column.cellClassName,
                    )}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
