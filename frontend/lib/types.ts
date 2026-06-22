export type ProcessStatus =
  | "pendente"
  | "rodando"
  | "concluido"
  | "concluido_com_erros"
  | "erro";

export interface ProcessProgress {
  erros?: string[];
  [key: string]: boolean | number | string | string[] | null | undefined;
}

export interface ProcessRecord {
  id: string;
  tipo: string;
  alvo: string;
  status: ProcessStatus;
  etapa_atual: string | null;
  progresso: ProcessProgress | null;
  erro: string | null;
  criado_em: string;
  atualizado_em: string;
}

export interface ProcessCreatedResponse {
  process_id: string;
}

export interface PortfolioItem {
  ticker_deb: string;
  nome_emissor: string;
  grupo_economico: string | null;
  setor: string | null;
  tipo_capital: string | null;
  tipo: string | null;
  data_emissao: string | null;
  data_vencimento: string | null;
  volume_emissao: number | string | null;
  indexador: string | null;
  spread_emissao: number | string | null;
  especie: string | null;
  rating_emissao: string | null;
  agencia_rating: string | null;
  perspectiva_rating: string | null;
  lei_incentivo: boolean | string | null;
  agente_fiduciario: string | null;
  status: string | null;
}

export interface AgendaEventoResumo {
  data_evento: string;
  ticker_deb: string;
  emissor: string;
  grupo_economico: string | null;
  evento: string | null;
  evento_arc: string | null;
  taxa: number | string | null;
  valor: number | string | null;
  status: string | null;
  dias_para_evento: number | string | null;
}

export interface AssetPaymentEvent {
  id: number;
  data_evento: string;
  data_liquidacao: string | null;
  data_base: string | null;
  evento: string | null;
  evento_arc: string | null;
  taxa: number | string | null;
  valor: number | string | null;
  status: string | null;
  grupo_status: string | null;
  criado_em: string | null;
}

export interface AssetDailyHistoryItem {
  id: number;
  data_referencia: string;
  pu_par: number | string | null;
  vna: number | string | null;
  juros: number | string | null;
  prazo_remanescente: number | string | null;
  pu_indicativo: number | string | null;
  taxa_indicativa: number | string | null;
  taxa_compra: number | string | null;
  taxa_venda: number | string | null;
  duration_dias_uteis: number | string | null;
  desvio_padrao: number | string | null;
  percentual_pu_par: number | string | null;
  percentual_vne: number | string | null;
  intervalo_indicativo_min: number | string | null;
  intervalo_indicativo_max: number | string | null;
  referencia_ntnb: string | null;
  spread_indicativo: number | string | null;
  volume_financeiro: number | string | null;
  quantidade_negocios: number | string | null;
  quantidade_titulos: number | string | null;
  taxa_media_negocios: number | string | null;
  pu_medio_negocios: number | string | null;
  reune: string | null;
  percentual_reune: number | string | null;
  pu_indicativo_status: string | null;
  taxa_indicativa_status: string | null;
  flag_status: string | null;
  data_ultima_atualizacao: string | null;
  criado_em: string | null;
}

export interface AssetCharacteristics {
  id: number;
  cnpj: string;
  ticker_deb: string;
  nome_emissor: string | null;
  tipo: string | null;
  serie: string | null;
  numero_emissao: number | string | null;
  data_emissao: string | null;
  data_vencimento: string | null;
  data_primeiro_pagamento: string | null;
  prazo_anos: number | string | null;
  volume_emissao: number | string | null;
  valor_unitario_emissao: number | string | null;
  quantidade_debentures: number | string | null;
  indexador: string | null;
  spread_emissao: number | string | null;
  taxa_prefixada: number | string | null;
  periodicidade_juros: string | null;
  periodicidade_amort: string | null;
  especie: string | null;
  garantias: string | null;
  garantidores: string | null;
  lei_incentivo: boolean | string | null;
  banco_coordenador: string | null;
  banco_estruturador: string | null;
  agente_fiduciario: string | null;
  banco_liquidante: string | null;
  rating_emissao: string | null;
  agencia_rating: string | null;
  data_ultimo_rating: string | null;
  perspectiva_rating: string | null;
  status: string | null;
  isin: string | null;
  codigo_cetip: string | null;
  atualizado_em: string | null;
}

export interface AssetDetail {
  ticker_deb: string;
  emissor: Emissor | null;
  caracteristicas: AssetCharacteristics;
  agenda_eventos: AssetPaymentEvent[];
  historico_diario: AssetDailyHistoryItem[];
  historico_total: number;
  historico_tem_mais: boolean;
}

export interface AssetSearchOption {
  id: string;
  value: string;
  primary: string;
  secondary: string;
  tipo: "ativo" | "emissor";
}

export interface AssetHistoryPage {
  ticker_deb: string;
  items: AssetDailyHistoryItem[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface Emissor {
  cnpj: string;
  cod_cvm: string | null;
  nome: string;
  categoria_cvm: string | null;
  tipo_capital: string | null;
  ticker_acao: string | null;
  grupo_economico: string | null;
  setor: string | null;
  observacao: string | null;
  criado_em: string | null;
  atualizado_em: string | null;
}

export interface EmissorDebenture {
  cnpj: string;
  nome: string;
  grupo_economico: string | null;
  tipo_capital: string | null;
  ticker_deb: string;
  status: string | null;
  indexador: string | null;
  spread_emissao: number | string | null;
  data_vencimento: string | null;
  rating_emissao: string | null;
  agencia_rating: string | null;
  lei_incentivo: boolean | string | null;
}

export interface EmissorDetail {
  emissor: Emissor;
  debentures: EmissorDebenture[];
}

export interface EmissorResolution {
  tipo_identificador: "cnpj" | "ticker_deb" | "ticker_acao";
  identificador: string;
  cnpj: string;
  ticker_deb?: string | null;
  ticker_acao?: string | null;
  emissor: Emissor;
}

export interface FinancialStatementRow {
  id: number;
  data_ref: string;
  tipo_doc: string;
  demonstracao: string;
  cd_conta: string;
  ds_conta: string | null;
  valor: number | string | null;
  criado_em: string | null;
}

export interface QuantitativeManifest {
  id: number;
  nome_arquivo: string;
  hash_md5: string;
  titulo?: string | null;
  criado_em: string | null;
}

export interface MarkdownDocument {
  id: string;
  tipo: "qualitativo" | "analise_credito" | "delta_analise";
  titulo: string;
  origem?: string | null;
  hash_md5?: string | null;
  financeiro?: boolean;
  criado_em?: string | null;
  conteudo: string;
}

export interface CreditAnalysis {
  id: number;
  cnpj: string;
  analise_markdown: string;
  delta_markdown: string | null;
  metadados: Record<string, unknown> | null;
  criado_em: string | null;
}

export interface StructuredStatements {
  cnpj: string;
  cod_cvm?: string;
  periodos: Record<
    string,
    {
      tipo: string;
      demonstracoes: Record<
        string,
        Record<
          string,
          {
            cd_conta: string;
            ds_conta: string | null;
            valor: number | string | null;
          }
        >
      >;
    }
  >;
}

export interface EmissorVisaoCompleta {
  emissor: Emissor;
  debentures: EmissorDebenture[];
  demonstracoes_financeiras: FinancialStatementRow[];
  demonstracoes_estruturadas: StructuredStatements;
  compendios_quantitativos: QuantitativeManifest[];
  markdowns: MarkdownDocument[];
  ultima_analise_credito: CreditAnalysis | null;
}
