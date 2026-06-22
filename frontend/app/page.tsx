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
        <p className="mt-1 text-xs text-[var(--muted)]">{formatText(item.tipo)}</p>
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
  const today = new Date();
  const todayKey = [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0"),
  ].join("-");

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
    proximoVencimento:
      items
        .map((item) => item.data_vencimento)
        .filter(
          (date): date is string =>
            typeof date === "string" && date.length > 0 && date >= todayKey,
        )
        .sort()[0] ?? null,
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
        title="Mapa operacional da carteira de debêntures"
        description="Leitura consolidada dos ativos da base. O nome do emissor abre o Detalhe do Emissor e o ticker leva direto ao Detalhe do Ativo já filtrado."
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Operações ativas
          </p>
          <p className="mt-3 text-3xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            {summary.totalOperacoes}
          </p>
        </div>
        <div className="rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Volume emissões
          </p>
          <p className="mt-3 text-3xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            {formatCurrency(summary.totalVolume)}
          </p>
        </div>
        <div className="rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Incentivadas
          </p>
          <p className="mt-3 text-3xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            {summary.incentivadas}
          </p>
        </div>
        <div className="rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Próximo vencimento
          </p>
          <p className="mt-3 text-3xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            {formatDate(summary.proximoVencimento)}
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
