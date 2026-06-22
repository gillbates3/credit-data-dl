import { cn } from "@/lib/utils";

const neutralStatus =
  "border-l-[var(--line-strong)] bg-[var(--panel-strong)] text-[var(--muted)]";
const successStatus =
  "border-l-[var(--success)] bg-[var(--success-bg)] text-[var(--success)]";
const infoStatus =
  "border-l-[var(--info)] bg-[var(--info-bg)] text-[var(--info)]";
const warningStatus =
  "border-l-[var(--warning)] bg-[var(--warning-bg)] text-[var(--warning)]";
const dangerStatus =
  "border-l-[var(--danger)] bg-[var(--danger-bg)] text-[var(--danger)]";

const statusMap: Record<string, string> = {
  pendente: neutralStatus,
  rodando: infoStatus,
  concluido: successStatus,
  concluido_com_erros: warningStatus,
  erro: dangerStatus,
  ativo: successStatus,
  previsto: neutralStatus,
  qualitativo: warningStatus,
  "análise": infoStatus,
  analise: infoStatus,
  delta: warningStatus,
};

function formatLabel(status: string): string {
  const labels: Record<string, string> = {
    concluido_com_erros: "concluído com erros",
  };

  return labels[status] ?? status.replaceAll("_", " ");
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const normalized = (status ?? "indefinido").toLowerCase();

  return (
    <span
      className={cn(
        "inline-flex items-center border-l-2 px-2 py-1 font-mono text-[11px] leading-none uppercase tracking-[0.18em]",
        statusMap[normalized] ?? neutralStatus,
      )}
    >
      {formatLabel(normalized)}
    </span>
  );
}
