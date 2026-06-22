import type { ReactNode } from "react";
import Link from "next/link";

import { DataTable, type DataColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { FinancialStatementsTable } from "@/components/financial-statements-table";
import { IdentifierSearchForm } from "@/components/identifier-search-form";
import { MarkdownViewer } from "@/components/markdown-viewer";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { ApiError, apiGet } from "@/lib/api";
import { formatCnpj } from "@/lib/cnpj";
import {
  formatDate,
  formatDateTime,
  formatPercent,
  formatText,
} from "@/lib/format";
import type {
  EmissorDebenture,
  EmissorVisaoCompleta,
  EmissorResolution,
  QuantitativeManifest,
} from "@/lib/types";

function DebentureAssetLink({
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

const debentureColumns: DataColumn<EmissorDebenture>[] = [
  {
    key: "ticker",
    header: "Ticker",
    render: (item) => (
      <Link
        href={`/detalhe-ativo?identificador=${encodeURIComponent(item.ticker_deb)}`}
        className="nav-chip-link"
        data-size="sm"
      >
        {item.ticker_deb}
      </Link>
    ),
  },
  {
    key: "status",
    header: "Status",
    render: (item) => (
      <DebentureAssetLink ticker={item.ticker_deb}>
        <StatusBadge status={item.status} />
      </DebentureAssetLink>
    ),
  },
  {
    key: "indexador",
    header: "Indexador",
    render: (item) => (
      <DebentureAssetLink ticker={item.ticker_deb}>
        {formatText(item.indexador)}
      </DebentureAssetLink>
    ),
  },
  {
    key: "spread",
    header: "Spread",
    render: (item) => (
      <DebentureAssetLink ticker={item.ticker_deb}>
        {formatPercent(item.spread_emissao)}
      </DebentureAssetLink>
    ),
  },
  {
    key: "vencimento",
    header: "Vencimento",
    render: (item) => (
      <DebentureAssetLink ticker={item.ticker_deb}>
        {formatDate(item.data_vencimento)}
      </DebentureAssetLink>
    ),
  },
  {
    key: "rating",
    header: "Rating",
    render: (item) => (
      <DebentureAssetLink ticker={item.ticker_deb}>
        {formatText(item.rating_emissao)}
      </DebentureAssetLink>
    ),
  },
];

const manifestoColumns: DataColumn<QuantitativeManifest>[] = [
  {
    key: "arquivo",
    header: "Arquivo",
    render: (item) => (
      <div className="space-y-1">
        <p className="text-sm font-medium text-[var(--ink)]">
          {item.titulo || item.nome_arquivo}
        </p>
        <p className="font-mono text-xs text-[var(--muted)]">{item.nome_arquivo}</p>
      </div>
    ),
  },
  {
    key: "hash",
    header: "Hash",
    render: (item) => (
      <span className="font-mono text-xs text-[var(--muted)]">
        {item.hash_md5}
      </span>
    ),
  },
  {
    key: "criado",
    header: "Processado em",
    render: (item) => formatDateTime(item.criado_em),
  },
];

export default async function DetalheEmissorIdentificadorPage({
  params,
}: {
  params: Promise<{ identificador: string }>;
}) {
  const { identificador } = await params;
  let resolution: EmissorResolution | null = null;
  let issuerView: EmissorVisaoCompleta | null = null;
  let notFound = false;

  try {
    resolution = await apiGet<EmissorResolution>(
      `/emissores/resolver/${encodeURIComponent(identificador)}`,
      { revalidate: 30 },
    );
    issuerView = await apiGet<EmissorVisaoCompleta>(
      `/emissores/${resolution.cnpj}/visao-completa`,
      { revalidate: 30 },
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound = true;
    } else {
      throw error;
    }
  }

  if (notFound || !resolution || !issuerView) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Detalhe do Emissor"
          title="Emissor não encontrado"
          description={`A API respondeu 404 para o identificador ${identificador}.`}
          action={
            <Link
              href="/detalhe-emissor"
              className="inline-flex rounded-full border border-[var(--line)] bg-white px-4 py-2 text-sm text-[var(--ink)] transition hover:border-[var(--line-strong)]"
            >
              Voltar à busca
            </Link>
          }
        />
        <EmptyState
          title="Nada encontrado para esse identificador"
          description="Tente novamente com o CNPJ do emissor ou com um ticker já mapeado para a empresa."
        />
      </div>
    );
  }

  const { emissor } = issuerView;
  const periodCount = Object.keys(
    issuerView.demonstracoes_estruturadas.periodos ?? {},
  ).length;
  const resolutionDescription =
    resolution.tipo_identificador === "ticker_deb"
      ? `Ticker de emissão ${resolution.identificador}`
      : resolution.tipo_identificador === "ticker_acao"
        ? `Ticker de ação ${resolution.identificador}`
        : `CNPJ ${formatCnpj(resolution.cnpj)}`;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Detalhe do Emissor"
        title={emissor.nome}
        description={`Visão consolidada do emissor ${formatCnpj(emissor.cnpj)}. Abertura resolvida por ${resolutionDescription}.`}
        action={
          <div className="flex flex-wrap gap-2">
            <Link
              href="/detalhe-emissor"
              className="inline-flex rounded-full border border-[var(--line)] bg-white px-4 py-2 text-sm text-[var(--ink)] transition hover:border-[var(--line-strong)]"
            >
              Nova busca
            </Link>
          </div>
        }
      />

      <IdentifierSearchForm
        basePath="/detalhe-emissor"
        buttonLabel="Buscar outro emissor"
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Debêntures
          </p>
          <p className="mt-3 text-3xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            {issuerView.debentures.length}
          </p>
        </div>
        <div className="rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Linhas financeiras
          </p>
          <p className="mt-3 text-3xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            {issuerView.demonstracoes_financeiras.length}
          </p>
        </div>
        <div className="rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Períodos financeiros
          </p>
          <p className="mt-3 text-3xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            {periodCount}
          </p>
        </div>
        <div className="rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Markdowns
          </p>
          <p className="mt-3 text-3xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            {issuerView.markdowns.length}
          </p>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[0.95fr_1.05fr]">
        <div className="rounded-2xl border border-[var(--line)] bg-white p-6 shadow-[var(--shadow-card)]">
          <h2 className="text-lg font-semibold tracking-[0.01em] text-[var(--ink)]">
            Cadastro do emissor
          </h2>
          <dl className="mt-5 grid gap-4 sm:grid-cols-2">
            <div>
              <dt className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
                CNPJ
              </dt>
              <dd className="mt-1 text-sm text-[var(--ink)]">
                {formatCnpj(emissor.cnpj)}
              </dd>
            </div>
            <div>
              <dt className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
                Ticker da ação
              </dt>
              <dd className="mt-1 text-sm text-[var(--ink)]">
                {formatText(emissor.ticker_acao)}
              </dd>
            </div>
            <div>
              <dt className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
                Tipo de capital
              </dt>
              <dd className="mt-1 text-sm text-[var(--ink)]">
                {formatText(emissor.tipo_capital)}
              </dd>
            </div>
            <div>
              <dt className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
                Grupo econômico
              </dt>
              <dd className="mt-1 text-sm text-[var(--ink)]">
                {formatText(emissor.grupo_economico)}
              </dd>
            </div>
            <div>
              <dt className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
                Setor
              </dt>
              <dd className="mt-1 text-sm text-[var(--ink)]">
                {formatText(emissor.setor)}
              </dd>
            </div>
            <div>
              <dt className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
                Atualizado em
              </dt>
              <dd className="mt-1 text-sm text-[var(--ink)]">
                {formatDateTime(emissor.atualizado_em)}
              </dd>
            </div>
          </dl>
        </div>

        {issuerView.debentures.length > 0 ? (
          <DataTable
            columns={debentureColumns}
            rows={issuerView.debentures}
            rowKey={(item) => item.ticker_deb}
            rowClassName="transition hover:bg-[var(--panel)]"
          />
        ) : (
          <EmptyState
            title="Sem debêntures vinculadas"
            description="O emissor foi encontrado, mas ainda não há títulos associados na base."
          />
        )}
      </section>

      {issuerView.demonstracoes_financeiras.length > 0 ? (
        <FinancialStatementsTable rows={issuerView.demonstracoes_financeiras} />
      ) : (
        <EmptyState
          title="Sem linhas financeiras estruturadas"
          description="Este emissor ainda não tem dados em `demonstracoes_financeiras`."
        />
      )}

      {issuerView.markdowns.length > 0 ? (
        <MarkdownViewer documents={issuerView.markdowns} />
      ) : (
        <EmptyState
          title="Sem markdowns disponíveis"
          description="Quando o processamento qualitativo ou a análise de crédito gravarem conteúdo markdown, ele aparecerá aqui."
        />
      )}

      {issuerView.compendios_quantitativos.length > 0 ? (
        <DataTable
          columns={manifestoColumns}
          rows={issuerView.compendios_quantitativos}
          rowKey={(item) => `${item.id}`}
        />
      ) : (
        <EmptyState
          title="Sem manifesto quantitativo"
          description="Ainda não há registro de PDFs quantitativos processados para este emissor."
        />
      )}
    </div>
  );
}
