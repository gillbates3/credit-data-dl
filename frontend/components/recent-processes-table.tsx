import Link from "next/link";

import { DataTable, type DataColumn } from "@/components/data-table";
import { StatusBadge } from "@/components/status-badge";
import { formatCnpj } from "@/lib/cnpj";
import {
  formatDateTime,
  formatRotulo,
  formatText,
} from "@/lib/format";
import type { ProcessRecord } from "@/lib/types";

function formatRecentProcessTarget(process: ProcessRecord): {
  primary: string;
  secondary: string | null;
} {
  const nomeEmissor =
    typeof process.progresso?.nome_emissor === "string"
      ? process.progresso.nome_emissor.trim()
      : "";
  const alvo = (process.alvo ?? "").trim();
  const alvoEhCnpj = alvo.replace(/\D/g, "").length === 14;

  if (nomeEmissor && alvoEhCnpj) {
    return {
      primary: nomeEmissor,
      secondary: formatCnpj(alvo),
    };
  }

  return {
    primary: formatText(alvo),
    secondary: null,
  };
}

const columns: DataColumn<ProcessRecord>[] = [
  {
    key: "alvo",
    header: "Alvo",
    render: (process) => {
      const alvo = formatRecentProcessTarget(process);

      return (
        <div className="space-y-1">
          <Link
            href={`/cadastro-dados?processo=${encodeURIComponent(process.id)}`}
            className="font-medium text-[var(--ink)] transition hover:text-[var(--accent)]"
          >
            {alvo.primary}
          </Link>
          {alvo.secondary ? (
            <p className="text-xs text-[var(--muted)]">{alvo.secondary}</p>
          ) : null}
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">
            {process.id}
          </p>
        </div>
      );
    },
  },
  {
    key: "tipo",
    header: "Tipo",
    render: (process) => formatRotulo(process.tipo),
  },
  {
    key: "status",
    header: "Status",
    render: (process) => <StatusBadge status={process.status} />,
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
