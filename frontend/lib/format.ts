function coerceNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function coerceDate(value: string | null | undefined): Date | null {
  if (!value) {
    return null;
  }

  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value: string | null | undefined): string {
  const date = coerceDate(value);
  if (!date) {
    return "—";
  }

  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeZone: "UTC",
  }).format(date);
}

export function formatDateTime(value: string | null | undefined): string {
  const date = coerceDate(value);
  if (!date) {
    return "—";
  }

  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

export function formatNumber(value: number | string | null | undefined): string {
  const parsed = coerceNumber(value);
  if (parsed === null) {
    return "—";
  }

  return new Intl.NumberFormat("pt-BR").format(parsed);
}

export function formatCurrency(value: number | string | null | undefined): string {
  const parsed = coerceNumber(value);
  if (parsed === null) {
    return "—";
  }

  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
    maximumFractionDigits: 0,
  }).format(parsed);
}

export function formatPercent(value: number | string | null | undefined): string {
  const parsed = coerceNumber(value);
  if (parsed === null) {
    return "—";
  }

  return new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(parsed) + "%";
}

export function formatBooleanFlag(value: boolean | string | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  if (typeof value === "boolean") {
    return value ? "Sim" : "Não";
  }

  const normalized = value.toString().trim().toLowerCase();
  if (["true", "sim", "s", "1"].includes(normalized)) {
    return "Sim";
  }
  if (["false", "nao", "não", "n", "0"].includes(normalized)) {
    return "Não";
  }

  return value;
}

export function formatText(value: string | null | undefined): string {
  return value?.trim() || "—";
}

// Acrônimos que devem aparecer em caixa-alta (não só com a 1ª letra maiúscula).
// Chave em minúsculo; comparação token a token. Estender conforme necessário.
const ACRONIMOS_ROTULO: Record<string, string> = {
  cvm: "CVM",
  ia: "IA",
  cnpj: "CNPJ",
  isin: "ISIN",
};

// Formata rótulos de controle/enum gravados em minúsculo pelo pipeline
// (ex.: tipo, etapa_atual): troca "_" por espaço, expande acrônimos conhecidos
// (cvm → CVM) e deixa a 1ª letra maiúscula. NÃO usar em nomes próprios,
// tickers, ISIN ou ratings (ex.: "brAAA").
export function formatRotulo(value: string | null | undefined): string {
  const text = value?.trim();
  if (!text) {
    return "—";
  }

  const palavras = text.split(/[\s_]+/).map((palavra, indice) => {
    const minuscula = palavra.toLowerCase();
    if (ACRONIMOS_ROTULO[minuscula]) {
      return ACRONIMOS_ROTULO[minuscula];
    }
    if (indice === 0) {
      return minuscula.charAt(0).toUpperCase() + minuscula.slice(1);
    }
    return minuscula;
  });

  return palavras.join(" ");
}

// Rótulos descritivos (da ação em andamento) para cada etapa do pipeline.
// A chave é o enum estável que o orquestrador grava em `etapa_atual`.
const ETAPA_ROTULOS: Record<string, string> = {
  // Fluxo de cadastro por ticker
  identidade: "Identificando emissor na ANBIMA",
  cvm: "Acessando DFs na CVM",
  mercado: "Acessando características na ANBIMA",
  // Fluxo de upload de documentos (PDFs)
  validacao_emissor: "Validando emissor",
  peek_hashes: "Verificando duplicatas",
  ia_quant: "Extraindo DFs dos PDFs (IA)",
  ia_qual: "Transcrevendo PDFs (IA)",
  finalizado: "Finalizando",
};

// Quando o processo já terminou, a "etapa atual" mostra o desfecho — não a
// última etapa técnica que rodou (que confunde, ex.: "Mercado" num concluído).
const STATUS_DESFECHO: Record<string, string> = {
  concluido: "Concluído",
  concluido_com_erros: "Concluído com avisos",
  erro: "Falhou",
};

// Texto humano para o card/coluna "Etapa atual" de um processo.
export function rotuloEtapaProcesso(
  etapa: string | null | undefined,
  status: string | null | undefined,
): string {
  const desfecho = status ? STATUS_DESFECHO[status.trim().toLowerCase()] : undefined;
  if (desfecho) {
    return desfecho;
  }
  const chave = etapa?.trim().toLowerCase();
  if (!chave) {
    return "—";
  }
  return ETAPA_ROTULOS[chave] ?? formatRotulo(etapa);
}
