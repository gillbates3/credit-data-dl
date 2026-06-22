import type { ProcessStatus } from "@/lib/types";

export const TERMINAL_PROCESS_STATUSES = new Set<ProcessStatus>([
  "concluido",
  "concluido_com_erros",
  "erro",
]);

export function isTerminalProcessStatus(status: ProcessStatus): boolean {
  return TERMINAL_PROCESS_STATUSES.has(status);
}

const progressLabels: Record<string, string> = {
  periodos_cvm: "Períodos CVM",
  eventos_agenda: "Eventos de agenda",
  dias_historico: "Dias de histórico",
  quant_processados: "Quantitativos processados",
  qual_processados: "Qualitativos processados",
  qual_fallback: "Qualitativos via texto bruto",
  qual_sem_conteudo: "Qualitativos sem conteúdo",
  pulados_quant: "Quantitativos pulados",
  pulados_qual: "Qualitativos pulados",
  passos_concluidos: "Passos concluídos",
};

export function formatProgressLabel(key: string): string {
  return (
    progressLabels[key] ??
    key
      .split("_")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ")
  );
}
