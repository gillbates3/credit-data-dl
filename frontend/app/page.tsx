import type { ReactNode } from "react";
import Link from "next/link";

import { DataTable, type DataColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { apiGet } from "@/lib/api";
import {
  formatCurrency,
  formatDate,
  formatPercent,
  formatRotulo,
  formatText,
} from "@/lib/format";
import type { PortfolioItem } from "@/lib/types";

// Renderiza sob demanda (não pré-renderiza no build, que rodaria sem a API no ar).
// O fetch com `revalidate` continua usando o Data Cache em runtime.
export const dynamic = "force-dynamic";

function AssetCellLink({
  ticker,
  children,
}: {
  ticker: string;
  children: ReactNode;
}) {
  return (
    <Link
      href={`/detalhe-ativo?identificador=${encodeURIComponent(ticker)}`}
      className="block transition hover:text-[var(--accent)]"
    >
      {children}
    </Link>
  );
}

const columns: DataColumn<PortfolioItem>[] = [
  {
    key: "ticker",
    header: "Ticker",
    render: (item) => (
      <div>
        <Link
          href={`/detalhe-ativo?identificador=${encodeURIComponent(item.ticker_deb)}`}
          className="nav-chip-link"
          data-size="sm"
        >
          {item.ticker_deb}
        </Link>
        <p className="mt-1 text-xs text-[var(--muted)]">{formatRotulo(item.tipo)}</p>
      </div>
    ),
  },
  {
    key: "emissor",
    header: "Emissor",
    render: (item) => (
      <div>
        <Link
          href={`/detalhe-emissor/${encodeURIComponent(item.ticker_deb)}`}
          className="nav-chip-link"
          data-size="sm"
        >
          {item.nome_emissor}
        </Link>
        <p className="mt-1 text-xs text-[var(--muted)]">
          {formatText(item.grupo_economico)}
        </p>
      </div>
    ),
  },
  {
    key: "indexador",
    header: "Indexador",
    render: (item) => (
      <AssetCellLink ticker={item.ticker_deb}>
        {formatText(item.indexador)}
      </AssetCellLink>
    ),
  },
  {
    key: "spread",
    header: "Spread",
    render: (item) => (
      <AssetCellLink ticker={item.ticker_deb}>
        {formatPercent(item.spread_emissao)}
      </AssetCellLink>
    ),
  },
  {
    key: "vencimento",
    header: "Vencimento",
    render: (item) => (
      <AssetCellLink ticker={item.ticker_deb}>
        {formatDate(item.data_vencimento)}
      </AssetCellLink>
    ),
  },
  {
    key: "rating",
    header: "Rating",
    render: (item) => (
      <AssetCellLink ticker={item.ticker_deb}>
        <div>
          <p>{formatText(item.rating_emissao)}</p>
          <p className="mt-1 text-xs text-[var(--muted)]">
            {formatText(item.agencia_rating)}
          </p>
        </div>
      </AssetCellLink>
    ),
  },
  {
    key: "status",
    header: "Status",
    render: (item) => (
      <AssetCellLink ticker={item.ticker_deb}>
        <StatusBadge status={item.status} />
      </AssetCellLink>
    ),
  },
];

function summarizePortfolio(items: PortfolioItem[]) {
  const totalVolume = items.reduce((sum, item) => {
    const numeric = Number(item.volume_emissao);
    return Number.isFinite(numeric) ? sum + numeric : sum;
  }, 0);

  const incentivadas = items.filter((item) => {
    const value = item.lei_incentivo;
    return value === true || value === "true" || value === "Sim";
  }).length;

  return {
    totalOperacoes: items.length,
    totalVolume,
    incentivadas,
    naoIncentivadas: items.length - incentivadas,
  };
}

export default async function HomePage() {
  const portfolio = await apiGet<PortfolioItem[]>("/portfolio", {
    revalidate: 30,
  });
  const summary = summarizePortfolio(portfolio);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Visão Geral"
        title="Mapa das debêntures cadastradas"
        description="Clique no ticker ou no nome do emissor para mais detalhes."
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-[1.1fr_1.2fr_1.38fr_2.12fr]">
        <div className="flex min-h-[118px] flex-col justify-between rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="whitespace-nowrap font-mono text-[0.72rem] leading-none uppercase tracking-[0.18em] text-[var(--muted)]">
            Quantidade total
          </p>
          <p className="mt-3 text-[clamp(2rem,2.6vw,2.6rem)] leading-none font-semibold tracking-[0.01em] tabular-nums text-[var(--ink)]">
            {summary.totalOperacoes}
          </p>
        </div>
        <div className="flex min-h-[118px] flex-col justify-between rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="whitespace-nowrap font-mono text-[0.72rem] leading-none uppercase tracking-[0.18em] text-[var(--muted)]">
            Incentivadas
          </p>
          <p className="mt-3 text-[clamp(2rem,2.6vw,2.6rem)] leading-none font-semibold tracking-[0.01em] tabular-nums text-[var(--ink)]">
            {summary.incentivadas}
          </p>
        </div>
        <div className="flex min-h-[118px] flex-col justify-between rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="whitespace-nowrap font-mono text-[0.72rem] leading-none uppercase tracking-[0.18em] text-[var(--muted)]">
            Não incentivadas
          </p>
          <p className="mt-3 text-[clamp(2rem,2.6vw,2.6rem)] leading-none font-semibold tracking-[0.01em] tabular-nums text-[var(--ink)]">
            {summary.naoIncentivadas}
          </p>
        </div>
        <div className="flex min-h-[118px] flex-col justify-between rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="whitespace-nowrap font-mono text-[0.72rem] leading-none uppercase tracking-[0.18em] text-[var(--muted)]">
            Volume emissões
          </p>
          <p className="mt-3 overflow-hidden text-[clamp(2rem,2.45vw,2.75rem)] leading-none font-semibold tracking-[0.01em] tabular-nums text-[var(--ink)]">
            {formatCurrency(summary.totalVolume)}
          </p>
        </div>
      </section>

      {portfolio.length > 0 ? (
        <DataTable
          columns={columns}
          rows={portfolio}
          rowKey={(item) => item.ticker_deb}
          rowClassName="transition hover:bg-[var(--panel)]"
        />
      ) : (
        <EmptyState
          title="Nenhuma operação ativa encontrada"
          description="Quando a API tiver dados no read-model de portfólio, eles aparecerão aqui automaticamente."
        />
      )}
    </div>
  );
}
