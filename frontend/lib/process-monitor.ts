import type { ProcessRecord, ProcessStatus } from "@/lib/types";

export const TERMINAL_PROCESS_STATUSES = new Set<ProcessStatus>([
  "concluido",
  "concluido_com_erros",
  "erro",
]);

export function isTerminalProcessStatus(status: ProcessStatus): boolean {
  return TERMINAL_PROCESS_STATUSES.has(status);
}

export type EstadoEtapa =
  | "concluida"
  | "pulada"
  | "atual"
  | "falhou"
  | "pendente";

export interface EstacaoProcesso {
  key: string;
  rotulo: string;
  estado: EstadoEtapa;
}

interface DefEstacao {
  key: string;
  rotulo: string;
  passoConcluido?: string;
  passoPulado?: string;
}

const FLUXO_TICKER: DefEstacao[] = [
  { key: "identidade", rotulo: "Identidade" },
  { key: "cvm", rotulo: "CVM", passoPulado: "cvm_pulado" },
  { key: "mercado", rotulo: "Mercado" },
];

const FLUXO_DOCUMENTOS: DefEstacao[] = [
  { key: "validacao_emissor", rotulo: "Validação do emissor" },
  { key: "peek_hashes", rotulo: "Check de doc. duplicado" },
  { key: "ia_quant", rotulo: "Extração de DFs (IA)" },
  { key: "ia_qual", rotulo: "Transcrição de PDFs (IA)" },
  { key: "finalizado", rotulo: "Conclusão do cadastro" },
];

function definirFluxo(process: ProcessRecord): DefEstacao[] {
  const etapa = process.etapa_atual?.trim().toLowerCase();
  if (etapa) {
    if (FLUXO_TICKER.some((estacao) => estacao.key === etapa)) {
      return FLUXO_TICKER;
    }
    if (FLUXO_DOCUMENTOS.some((estacao) => estacao.key === etapa)) {
      return FLUXO_DOCUMENTOS;
    }
  }

  const digitos = (process.alvo ?? "").replace(/\D/g, "");
  return digitos.length >= 14 ? FLUXO_DOCUMENTOS : FLUXO_TICKER;
}

export function computarEtapas(process: ProcessRecord): EstacaoProcesso[] {
  const fluxo = definirFluxo(process);
  const etapa = process.etapa_atual?.trim().toLowerCase() ?? null;
  const passos = Array.isArray(process.progresso?.passos_concluidos)
    ? process.progresso.passos_concluidos.map((passo) => passo.toLowerCase())
    : [];
  const terminal = isTerminalProcessStatus(process.status);
  const falhou = process.status === "erro";
  const idxAtual = fluxo.findIndex((estacao) => estacao.key === etapa);

  return fluxo.map((estacao, idx) => {
    const pulado =
      !!estacao.passoPulado && passos.includes(estacao.passoPulado);
    const concluido = passos.includes(estacao.passoConcluido ?? estacao.key);

    let estado: EstadoEtapa;
    if (pulado) {
      estado = "pulada";
    } else if (concluido) {
      estado = "concluida";
    } else if (falhou && estacao.key === etapa) {
      estado = "falhou";
    } else if (terminal) {
      estado = idxAtual >= 0 && idx <= idxAtual ? "concluida" : "pendente";
    } else if (estacao.key === etapa) {
      estado = "atual";
    } else if (idxAtual < 0 && idx === 0) {
      estado = "atual";
    } else if (idxAtual >= 0 && idx < idxAtual) {
      estado = "concluida";
    } else {
      estado = "pendente";
    }

    return { key: estacao.key, rotulo: estacao.rotulo, estado };
  });
}

const progressLabels: Record<string, string> = {
  nome_emissor: "Empresa",
  periodos_cvm: "Períodos CVM",
  eventos_agenda: "Eventos de agenda",
  dias_historico: "Dias de histórico",
  quant_processados: "Docs Aproveitados (Quant)",
  qual_processados: "Docs Aproveitados (Quali)",
  qual_fallback: "Fall back: Extrair texto bruto",
  qual_sem_conteudo: "Qualitativos sem conteúdo",
  pulados_quant: "Docs Já Existentes (Quant)",
  pulados_qual: "Docs Já Existentes (Quali)",
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
