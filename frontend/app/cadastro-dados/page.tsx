import { EmptyState } from "@/components/empty-state";
import { DocumentRegistrationForm } from "@/components/document-registration-form";
import { TickerRegistrationForm } from "@/components/ticker-registration-form";
import { ProcessMonitorClient } from "@/components/process-monitor-client";
import { RecentProcessesTable } from "@/components/recent-processes-table";
import { PageHeader } from "@/components/page-header";
import { ApiError, apiGet } from "@/lib/api";
import type { AssetDetail, ProcessRecord } from "@/lib/types";

import { registerTickerAction } from "@/app/cadastro-dados/actions";

export default async function CadastroDadosPage({
  searchParams,
}: {
  searchParams: Promise<{ processo?: string }>;
}) {
  const { processo: processId } = await searchParams;
  // Esta tela só usa ticker + nome do emissor para o dropdown; `resumo=1` evita
  // baixar agenda e histórico diário de todos os ativos à toa.
  const [assets, processes] = await Promise.all([
    apiGet<AssetDetail[]>("/ativos?resumo=1", { revalidate: 30 }),
    apiGet<ProcessRecord[]>("/processos", { revalidate: 15 }),
  ]);

  let currentProcess: ProcessRecord | null = null;
  if (processId) {
    try {
      currentProcess = await apiGet<ProcessRecord>(`/processos/${processId}`);
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 404)) {
        throw error;
      }
    }
  }

  const assetOptions = assets.map((item) => ({
    value: item.ticker_deb,
    label: `${item.ticker_deb} · ${item.emissor?.nome ?? item.caracteristicas.nome_emissor ?? "Emissor sem nome"}`,
  }));

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Cadastro de Dados"
        title="Entrada operacional da base"
        description="Cadastre tickers e documentos na mesma tela. O acompanhamento do processo atual e o histórico recente aparecem logo abaixo, sem sair do fluxo."
      />

      <section className="grid gap-6 xl:grid-cols-2">
        <TickerRegistrationForm action={registerTickerAction} />
        <DocumentRegistrationForm assetOptions={assetOptions} />
      </section>

      {currentProcess ? (
        <section className="space-y-4">
          <div className="space-y-1 rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-5 shadow-[var(--shadow-card)]">
            <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
              Processo atual
            </p>
            <h2 className="text-2xl font-semibold tracking-[0.01em] text-[var(--ink)]">
              Acompanhamento em tempo real
            </h2>
          </div>
          <ProcessMonitorClient initialProcess={currentProcess} />
        </section>
      ) : null}

      <section className="space-y-4">
        <div className="space-y-1 rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-5 shadow-[var(--shadow-card)]">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Processos recentes
          </p>
          <h2 className="text-2xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            Histórico operacional
          </h2>
        </div>

        {processes.length > 0 ? (
          <RecentProcessesTable processes={processes} />
        ) : (
          <EmptyState
            title="Nenhum processo disparado ainda"
            description="Depois do primeiro envio de ticker ou documento, o monitor de processos recentes aparecerá aqui automaticamente."
          />
        )}
      </section>
    </div>
  );
}
