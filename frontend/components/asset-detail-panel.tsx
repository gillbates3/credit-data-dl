import Link from "next/link";

import { AssetHistorySection } from "@/components/asset-history-section";
import { DataTable, type DataColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { StatusBadge } from "@/components/status-badge";
import { formatCnpj } from "@/lib/cnpj";
import {
  formatBooleanFlag,
  formatCurrency,
  formatDate,
  formatDateTime,
  formatNumber,
  formatPercent,
  formatRotulo,
  formatText,
} from "@/lib/format";
import type { AssetDetail, AssetPaymentEvent } from "@/lib/types";

const eventColumns: DataColumn<AssetPaymentEvent>[] = [
  {
    key: "data_evento",
    header: "Evento",
    render: (item) => (
      <div>
        <p className="font-medium text-[var(--ink)]">{formatDate(item.data_evento)}</p>
        <p className="mt-1 text-xs text-[var(--muted)]">
          {formatText(item.evento_arc || item.evento)}
        </p>
      </div>
    ),
  },
  {
    key: "datas",
    header: "Base / liquidação",
    render: (item) => (
      <div className="space-y-1 text-xs text-[var(--muted)]">
        <p>Base: {formatDate(item.data_base)}</p>
        <p>Liquidação: {formatDate(item.data_liquidacao)}</p>
      </div>
    ),
  },
  {
    key: "taxa",
    header: "Taxa",
    render: (item) => formatPercent(item.taxa),
  },
  {
    key: "valor",
    header: "Valor",
    render: (item) => formatCurrency(item.valor),
  },
  {
    key: "status",
    header: "Status",
    render: (item) => <StatusBadge status={item.status} />,
  },
];

function DefinitionItem({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div>
      <dt className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
        {label}
      </dt>
      <dd className="mt-1 text-sm text-[var(--ink)]">{value}</dd>
    </div>
  );
}

export function AssetDetailPanel({ asset }: { asset: AssetDetail }) {
  const { caracteristicas, emissor } = asset;
  const prazoAnos = formatNumber(caracteristicas.prazo_anos);

  return (
    <section className="space-y-4 rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)] md:p-6">
      <div className="flex flex-col gap-4 rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <p className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--muted)]">
            Ativo
          </p>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <h2 className="text-3xl font-semibold tracking-[0.01em] text-[var(--ink)]">
              {asset.ticker_deb}
            </h2>
            <Link
              href={`/detalhe-emissor/${encodeURIComponent(asset.ticker_deb)}`}
              className="nav-chip-link"
              data-size="sm"
            >
              {formatText(emissor?.nome ?? caracteristicas.nome_emissor)}
            </Link>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-[var(--muted)]">
            <span>CNPJ: {formatCnpj(caracteristicas.cnpj)}</span>
            <span>Indexador: {formatText(caracteristicas.indexador)}</span>
            <span>Vencimento: {formatDate(caracteristicas.data_vencimento)}</span>
            <span>Última atualização: {formatDateTime(caracteristicas.atualizado_em)}</span>
          </div>
        </div>

        <div className="lg:min-w-[13rem]">
          <div className="rounded-2xl border border-[var(--line)] bg-white px-4 py-3">
            <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
              Spread / taxa
            </p>
            <p className="mt-2 text-lg font-semibold tracking-[0.01em] text-[var(--ink)]">
              {formatPercent(caracteristicas.spread_emissao)}
            </p>
            <p className="mt-1 text-xs text-[var(--muted)]">
              Prefixada: {formatPercent(caracteristicas.taxa_prefixada)}
            </p>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.78fr_1.22fr]">
        <div className="rounded-2xl border border-[var(--line)] bg-white p-6 shadow-[var(--shadow-card)]">
          <div className="space-y-1">
            <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
              Características
            </p>
            <h3 className="text-xl font-semibold tracking-[0.01em] text-[var(--ink)]">
              Ficha completa do ativo
            </h3>
          </div>

          <dl className="mt-5 grid gap-4 sm:grid-cols-2">
            <DefinitionItem label="Tipo" value={formatRotulo(caracteristicas.tipo)} />
            <DefinitionItem label="Série" value={formatText(caracteristicas.serie)} />
            <DefinitionItem
              label="Número da emissão"
              value={formatNumber(caracteristicas.numero_emissao)}
            />
            <DefinitionItem
              label="Data de emissão"
              value={formatDate(caracteristicas.data_emissao)}
            />
            <DefinitionItem
              label="Primeiro evento"
              value={formatDate(caracteristicas.data_primeiro_pagamento)}
            />
            <DefinitionItem
              label="Prazo"
              value={prazoAnos === "—" ? "—" : `${prazoAnos} anos`}
            />
            <DefinitionItem
              label="Valor unitário"
              value={formatCurrency(caracteristicas.valor_unitario_emissao)}
            />
            <DefinitionItem
              label="Quantidade"
              value={formatNumber(caracteristicas.quantidade_debentures)}
            />
            <DefinitionItem
              label="Periodicidade juros"
              value={formatText(caracteristicas.periodicidade_juros)}
            />
            <DefinitionItem
              label="Periodicidade amort."
              value={formatText(caracteristicas.periodicidade_amort)}
            />
            <DefinitionItem
              label="Espécie"
              value={formatText(caracteristicas.especie)}
            />
            <DefinitionItem
              label="Lei incentivo"
              value={formatBooleanFlag(caracteristicas.lei_incentivo)}
            />
            <DefinitionItem
              label="Garantias"
              value={formatText(caracteristicas.garantias)}
            />
            <DefinitionItem
              label="Garantidores"
              value={formatText(caracteristicas.garantidores)}
            />
            <DefinitionItem
              label="Agente fiduciário"
              value={formatText(caracteristicas.agente_fiduciario)}
            />
            <DefinitionItem
              label="Banco liquidante"
              value={formatText(caracteristicas.banco_liquidante)}
            />
            <DefinitionItem
              label="Coordenador"
              value={formatText(caracteristicas.banco_coordenador)}
            />
            <DefinitionItem
              label="Estruturador"
              value={formatText(caracteristicas.banco_estruturador)}
            />
            <DefinitionItem
              label="Rating"
              value={formatText(caracteristicas.rating_emissao)}
            />
            <DefinitionItem
              label="Agência"
              value={formatText(caracteristicas.agencia_rating)}
            />
            <DefinitionItem
              label="Perspectiva"
              value={formatText(caracteristicas.perspectiva_rating)}
            />
            <DefinitionItem
              label="Data último rating"
              value={formatDate(caracteristicas.data_ultimo_rating)}
            />
            <DefinitionItem label="ISIN" value={formatText(caracteristicas.isin)} />
            <DefinitionItem
              label="CETIP"
              value={formatText(caracteristicas.codigo_cetip)}
            />
          </dl>
        </div>

        <div className="rounded-2xl border border-[var(--line)] bg-white p-6 shadow-[var(--shadow-card)]">
          <div className="space-y-1">
            <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
              Agenda
            </p>
            <h3 className="text-xl font-semibold tracking-[0.01em] text-[var(--ink)]">
              Cronograma de eventos do ativo
            </h3>
          </div>

          {asset.agenda_eventos.length > 0 ? (
            <div className="mt-4">
              <DataTable
                columns={eventColumns}
                rows={asset.agenda_eventos}
                rowKey={(item) => `${asset.ticker_deb}-${item.id}`}
                scrollClassName="max-h-[39rem] overflow-y-auto"
                stickyHeader
                rowClassName="hover:bg-[var(--panel)]"
              />
            </div>
          ) : (
            <div className="mt-4">
              <EmptyState
                title="Sem cronograma cadastrado"
                description="Os próximos eventos vão aparecer aqui assim que a agenda da debênture estiver populada no backend."
              />
            </div>
          )}
        </div>
      </div>

      <div className="rounded-2xl border border-[var(--line)] bg-white p-6 shadow-[var(--shadow-card)]">
        <div className="space-y-1">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Histórico diário
          </p>
          <h3 className="text-xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            PUs, taxas e métricas de mercado
          </h3>
        </div>

        <AssetHistorySection
          initialItems={asset.historico_diario}
          ticker={asset.ticker_deb}
          total={asset.historico_total}
          hasMore={asset.historico_tem_mais}
        />
      </div>
    </section>
  );
}
