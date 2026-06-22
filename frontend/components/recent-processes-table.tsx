import Link from "next/link";

import { DataTable, type DataColumn } from "@/components/data-table";
import { StatusBadge } from "@/components/status-badge";
import { formatDateTime, formatText } from "@/lib/format";
import type { ProcessRecord } from "@/lib/types";

const columns: DataColumn<ProcessRecord>[] = [
  {
    key: "alvo",
    header: "Alvo",
    render: (process) => (
      <div className="space-y-1">
        <Link
          href={`/cadastro-dados?processo=${encodeURIComponent(process.id)}`}
          className="font-medium text-[var(--ink)] transition hover:text-[var(--accent)]"
        >
          {process.alvo}
        </Link>
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">
          {process.id}
        </p>
      </div>
    ),
  },
  {
    key: "tipo",
    header: "Tipo",
    render: (process) => formatText(process.tipo),
  },
  {
    key: "status",
    header: "Status",
    render: (process) => <StatusBadge status={process.status} />,
  },
  {
    key: "etapa",
    header: "Etapa atual",
    render: (process) => formatText(process.etapa_atual),
  },
  {
    key: "atualizado",
    header: "Atualizado em",
    render: (process) => formatDateTime(process.atualizado_em),
  },
];

export function RecentProcessesTable({
  processes,
}: {
  processes: ProcessRecord[];
}) {
  return (
    <DataTable
      columns={columns}
      rows={processes}
      rowKey={(process) => process.id}
      rowClassName="transition hover:bg-[var(--panel)]"
    />
  );
}
