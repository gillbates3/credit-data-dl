import { AssetDetailPanel } from "@/components/asset-detail-panel";
import { AssetSelectorCombobox } from "@/components/asset-selector-combobox";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { ApiError, apiGet } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import type { AssetDetail } from "@/lib/types";

function summarizeAssets(assets: AssetDetail[]) {
  return {
    ativos: assets.length,
    eventos: assets.reduce((total, asset) => total + asset.agenda_eventos.length, 0),
    historicos: assets.reduce(
      (total, asset) => total + asset.historico_diario.length,
      0,
    ),
  };
}

export default async function DetalheAtivoPage({
  searchParams,
}: {
  searchParams: Promise<{ identificador?: string }>;
}) {
  const { identificador } = await searchParams;
  const filtered = Boolean(identificador);

  if (!filtered) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Detalhe do Ativo"
          title="Selecione um ativo ou emissor"
          description="Use a busca inteligente abaixo para localizar rapidamente por ticker, CNPJ ou ticker da ação. As alternativas aparecem conforme você digita."
        />

        <AssetSelectorCombobox key="asset-selector-empty" />
      </div>
    );
  }

  let assets: AssetDetail[] = [];
  let notFound = false;

  try {
    assets = await apiGet<AssetDetail[]>(
      `/ativos?identificador=${encodeURIComponent(identificador!)}`,
      { revalidate: 30 },
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound = true;
    } else {
      throw error;
    }
  }

  if (notFound) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Detalhe do Ativo"
          title="Ativo ou emissor não encontrado"
          description={`A API não encontrou dados para o identificador ${identificador}.`}
        />

        <AssetSelectorCombobox
          key={`asset-selector-${identificador}`}
          initialValue={identificador}
        />

        <EmptyState
          title="Nada encontrado para esse filtro"
          description="Tente buscar por um ticker de debênture, por um CNPJ ou por um ticker de ação já mapeado."
        />
      </div>
    );
  }

  const summary = summarizeAssets(assets);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Detalhe do Ativo"
        title={
          filtered
            ? "Leitura completa do ativo filtrado"
            : "Leitura completa do ativo selecionado"
        }
        description={
          filtered
            ? "A tela foi aberta já filtrada e consolida características, agenda de eventos e histórico diário do identificador selecionado."
            : "Selecione um ativo para abrir as características, agenda e histórico diário."
        }
      />

      <AssetSelectorCombobox
        key={`asset-selector-${identificador}`}
        initialValue={identificador}
      />

      <section className="grid gap-4 md:grid-cols-3">
        <div className="rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Ativos exibidos
          </p>
          <p className="mt-3 text-3xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            {formatNumber(summary.ativos)}
          </p>
        </div>
        <div className="rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Eventos de agenda
          </p>
          <p className="mt-3 text-3xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            {formatNumber(summary.eventos)}
          </p>
        </div>
        <div className="rounded-2xl border border-[var(--line)] bg-white p-5 shadow-[var(--shadow-card)]">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Leituras diárias
          </p>
          <p className="mt-3 text-3xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            {formatNumber(summary.historicos)}
          </p>
        </div>
      </section>

      {assets.length > 0 ? (
        <div className="space-y-6">
          {assets.map((asset) => (
            <AssetDetailPanel
              key={`${asset.ticker_deb}-${asset.historico_total}-${asset.historico_diario.length}`}
              asset={asset}
            />
          ))}
        </div>
      ) : (
        <EmptyState
          title="Sem ativos disponíveis"
          description="Quando a tabela de características estiver populada, os detalhes dos ativos aparecerão aqui automaticamente."
        />
      )}
    </div>
  );
}
