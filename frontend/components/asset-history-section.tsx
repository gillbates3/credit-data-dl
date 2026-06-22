"use client";

import { useState } from "react";

import { DataTable, type DataColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import {
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
  formatText,
} from "@/lib/format";
import type { AssetDailyHistoryItem, AssetHistoryPage } from "@/lib/types";

const historyColumns: DataColumn<AssetDailyHistoryItem>[] = [
  {
    key: "data_referencia",
    header: "Data",
    render: (item) => formatDate(item.data_referencia),
  },
  {
    key: "pu",
    header: "PUs",
    render: (item) => (
      <div className="space-y-1 text-xs text-[var(--muted)]">
        <p>Indicativo: {formatNumber(item.pu_indicativo)}</p>
        <p>Par: {formatNumber(item.pu_par)}</p>
        <p>Médio: {formatNumber(item.pu_medio_negocios)}</p>
      </div>
    ),
  },
  {
    key: "taxas",
    header: "Taxas",
    render: (item) => (
      <div className="space-y-1 text-xs text-[var(--muted)]">
        <p>Indicativa: {formatPercent(item.taxa_indicativa)}</p>
        <p>Compra: {formatPercent(item.taxa_compra)}</p>
        <p>Venda: {formatPercent(item.taxa_venda)}</p>
        <p>Média: {formatPercent(item.taxa_media_negocios)}</p>
      </div>
    ),
  },
  {
    key: "curva",
    header: "Curva",
    render: (item) => (
      <div className="space-y-1 text-xs text-[var(--muted)]">
        <p>VNA: {formatNumber(item.vna)}</p>
        <p>Juros: {formatNumber(item.juros)}</p>
        <p>Spread: {formatPercent(item.spread_indicativo)}</p>
        <p>Duration: {formatNumber(item.duration_dias_uteis)}</p>
      </div>
    ),
  },
  {
    key: "mercado",
    header: "Mercado",
    render: (item) => (
      <div className="space-y-1 text-xs text-[var(--muted)]">
        <p>Volume: {formatCurrency(item.volume_financeiro)}</p>
        <p>Negócios: {formatNumber(item.quantidade_negocios)}</p>
        <p>Títulos: {formatNumber(item.quantidade_titulos)}</p>
      </div>
    ),
  },
  {
    key: "status",
    header: "Status",
    render: (item) => (
      <div className="space-y-1 text-xs text-[var(--muted)]">
        <p>{formatText(item.pu_indicativo_status)}</p>
        <p>{formatText(item.taxa_indicativa_status)}</p>
        <p>Atualizado: {formatDate(item.data_ultima_atualizacao)}</p>
      </div>
    ),
  },
];

interface AssetHistorySectionProps {
  initialItems: AssetDailyHistoryItem[];
  ticker: string;
  total: number;
  hasMore: boolean;
}

export function AssetHistorySection({
  initialItems,
  ticker,
  total,
  hasMore,
}: AssetHistorySectionProps) {
  const [items, setItems] = useState(initialItems);
  const [canLoadMore, setCanLoadMore] = useState(hasMore);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadMore() {
    setIsLoading(true);
    setError(null);

    try {
      const remaining = Math.max(total - items.length, 0);
      const response = await fetch(
        `/api/detalhe-ativo/${encodeURIComponent(ticker)}/historico?offset=${items.length}&limit=${remaining}`,
        { cache: "no-store" },
      );
      const payload = (await response.json().catch(() => null)) as
        | AssetHistoryPage
        | { error?: string }
        | null;

      if (!response.ok) {
        throw new Error(payload && "error" in payload ? payload.error : "Falha na leitura.");
      }

      if (!payload || !("items" in payload)) {
        throw new Error("A resposta do histórico veio em formato inesperado.");
      }

      setItems((current) => [...current, ...payload.items]);
      setCanLoadMore(payload.has_more);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Não foi possível carregar o histórico mais antigo.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  if (items.length === 0) {
    return (
      <EmptyState
        title="Sem série diária disponível"
        description="Os campos de PU, taxas e demais métricas serão exibidos assim que o histórico diário for persistido para esse ativo."
      />
    );
  }

  return (
    <div className="mt-4 space-y-4">
      <DataTable
        columns={historyColumns}
        rows={items}
        rowKey={(item) => `${ticker}-${item.id}`}
        scrollClassName="max-h-[39rem] overflow-y-auto"
        stickyHeader
        rowClassName="hover:bg-[var(--panel)]"
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-[var(--muted)]">
          Mostrando {items.length} de {total} registros.
        </p>
        {canLoadMore ? (
          <button
            type="button"
            onClick={() => void loadMore()}
            disabled={isLoading}
            className="inline-flex items-center justify-center rounded-full border border-[var(--line)] bg-white px-4 py-2 text-sm font-medium text-[var(--ink)] transition hover:border-[var(--line-strong)] disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isLoading ? "Carregando..." : "Carregar histórico mais antigo"}
          </button>
        ) : null}
      </div>

      {error ? <p className="text-sm text-[var(--danger)]">{error}</p> : null}
    </div>
  );
}
