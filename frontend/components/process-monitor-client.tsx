"use client";

import {
  startTransition,
  useEffect,
  useEffectEvent,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";

import { EmptyState } from "@/components/empty-state";
import { ProcessStepper } from "@/components/process-stepper";
import { StatusBadge } from "@/components/status-badge";
import { formatCnpj } from "@/lib/cnpj";
import {
  formatDateTime,
  formatRotulo,
  formatText,
  rotuloEtapaProcesso,
} from "@/lib/format";
import {
  formatProgressLabel,
  isTerminalProcessStatus,
} from "@/lib/process-monitor";
import type { ProcessRecord } from "@/lib/types";

interface ProcessMonitorClientProps {
  initialProcess: ProcessRecord;
}

function formatProcessTarget(process: ProcessRecord): {
  primary: string;
  secondary: string | null;
} {
  const nomeEmissor =
    typeof process.progresso?.nome_emissor === "string"
      ? process.progresso.nome_emissor.trim()
      : "";
  const alvo = (process.alvo ?? "").trim();
  const alvoFormatado = formatCnpj(alvo);
  const alvoEhCnpj = alvo.replace(/\D/g, "").length === 14;

  if (nomeEmissor && alvoEhCnpj) {
    return {
      primary: nomeEmissor,
      secondary: alvoFormatado,
    };
  }

  return {
    primary: formatText(alvo),
    secondary: null,
  };
}

export function ProcessMonitorClient({
  initialProcess,
}: ProcessMonitorClientProps) {
  const router = useRouter();
  const [process, setProcess] = useState(initialProcess);
  const [pollError, setPollError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const messagesViewportRef = useRef<HTMLDivElement | null>(null);
  const previousStatusRef = useRef(initialProcess.status);

  useEffect(() => {
    previousStatusRef.current = initialProcess.status;
    setProcess(initialProcess);
    setPollError(null);
    setIsRefreshing(false);
  }, [initialProcess]);

  const refreshProcess = useEffectEvent(async () => {
    if (isTerminalProcessStatus(process.status)) {
      return;
    }

    setIsRefreshing(true);

    try {
      const response = await fetch(`/api/processos/${process.id}`, {
        cache: "no-store",
      });

      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as
          | { error?: string }
          | null;

        throw new Error(payload?.error || "Falha ao atualizar o processo.");
      }

      const nextProcess = (await response.json()) as ProcessRecord;
      startTransition(() => {
        setProcess(nextProcess);
      });
      setPollError(null);
    } catch (error) {
      setPollError(
        error instanceof Error ? error.message : "Falha ao atualizar o processo.",
      );
    } finally {
      setIsRefreshing(false);
    }
  });

  useEffect(() => {
    if (isTerminalProcessStatus(process.status)) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void refreshProcess();
    }, 2000);

    return () => window.clearInterval(intervalId);
  }, [process.id, process.status]);

  useEffect(() => {
    const previousStatus = previousStatusRef.current;
    previousStatusRef.current = process.status;

    const acabouDeConcluir =
      !isTerminalProcessStatus(previousStatus) &&
      isTerminalProcessStatus(process.status);
    const alvoEhCnpj = (process.alvo ?? "").replace(/\D/g, "").length === 14;
    const deveAtualizarCatalogo =
      acabouDeConcluir && process.status !== "erro" && !alvoEhCnpj;

    if (deveAtualizarCatalogo) {
      router.refresh();
    }
  }, [process.alvo, process.status, router]);

  const progress = process.progresso ?? {};
  const progressEntries = Object.entries(progress).flatMap(([key, value]) => {
    if (
      key === "erros" ||
      key === "passos_concluidos" ||
      key === "mensagem_andamento" ||
      key === "mensagens_andamento"
    ) {
      return [];
    }

    if (key === "periodos_cvm" && progress.nome_emissor) {
      return [];
    }

    if (key === "nome_emissor") {
      return value ? [["nome_emissor", value] as const] : [];
    }

    if (key === "cnpj") {
      return value ? [["cnpj", formatCnpj(String(value))] as const] : [];
    }

    return value !== null && value !== undefined ? [[key, value] as const] : [];
  });
  const progressErrors = Array.isArray(process.progresso?.erros)
    ? process.progresso.erros
    : [];
  const targetDisplay = formatProcessTarget(process);
  const liveStatusMessages = Array.isArray(process.progresso?.mensagens_andamento)
    ? process.progresso.mensagens_andamento.filter(
        (value): value is string => typeof value === "string" && value.trim().length > 0,
      )
    : typeof process.progresso?.mensagem_andamento === "string" &&
        process.progresso.mensagem_andamento.trim()
      ? [process.progresso.mensagem_andamento.trim()]
      : [];

  useEffect(() => {
    const viewport = messagesViewportRef.current;
    if (!viewport) {
      return;
    }
    viewport.scrollTop = viewport.scrollHeight;
  }, [liveStatusMessages.length]);

  return (
    <div className="space-y-6">
      <section className="grid gap-4 lg:grid-cols-[1.4fr_0.6fr]">
        <div className="rounded-2xl border border-[var(--line)] bg-white p-6 shadow-[var(--shadow-card)]">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-2">
              <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
                Processo {process.id}
              </p>
              <div className="flex flex-wrap items-center gap-3">
                <StatusBadge status={process.status} />
                <span className="text-sm text-[var(--muted)]">
                  {isTerminalProcessStatus(process.status)
                    ? "Polling encerrado"
                    : isRefreshing
                      ? "Atualizando..."
                      : "Aguardando próxima leitura"}
                </span>
              </div>
            </div>
            <div className="rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-4 py-3 text-right">
              <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
                Etapa atual
              </p>
              <p className="mt-1 text-sm font-medium text-[var(--ink)]">
                {rotuloEtapaProcesso(process.etapa_atual, process.status)}
              </p>
            </div>
          </div>

          {process.erro ? (
            <div className="mt-5 rounded-xl border border-[var(--danger-line)] bg-[var(--danger-bg)] px-4 py-3 text-sm text-[var(--danger)]">
              {process.erro}
            </div>
          ) : null}

          {pollError ? (
            <div className="mt-5 rounded-xl border border-[var(--warning-line)] bg-[var(--warning-bg)] px-4 py-3 text-sm text-[var(--warning)]">
              {pollError}
            </div>
          ) : null}

          <dl className="mt-6 grid gap-4 md:grid-cols-2">
            <div className="rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-4">
              <dt className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
                Tipo
              </dt>
              <dd className="mt-2 text-sm font-medium text-[var(--ink)]">
                {formatRotulo(process.tipo)}
              </dd>
            </div>
            <div className="rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-4">
              <dt className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
                Alvo
              </dt>
              <dd className="mt-2 text-sm font-medium text-[var(--ink)]">
                <span className="block">{targetDisplay.primary}</span>
                {targetDisplay.secondary ? (
                  <span className="mt-1 block text-xs font-normal text-[var(--muted)]">
                    {targetDisplay.secondary}
                  </span>
                ) : null}
              </dd>
            </div>
            <div className="rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-4">
              <dt className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
                Criado em
              </dt>
              <dd className="mt-2 text-sm font-medium text-[var(--ink)]">
                {formatDateTime(process.criado_em)}
              </dd>
            </div>
            <div className="rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-4">
              <dt className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
                Atualizado em
              </dt>
              <dd className="mt-2 text-sm font-medium text-[var(--ink)]">
                {formatDateTime(process.atualizado_em)}
              </dd>
            </div>
          </dl>

          <ProcessStepper process={process} />

          {liveStatusMessages.length > 0 ? (
            <div className="mt-4 px-1">
              <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
                Histórico da API
              </p>
              <div
                ref={messagesViewportRef}
                className="mt-2 max-h-32 overflow-y-auto rounded-2xl border border-[var(--line)] bg-white/70 px-4 py-3"
              >
                <ul className="space-y-2">
                  {liveStatusMessages.map((message, index) => (
                    <li
                      key={`${index}-${message}`}
                      className="font-mono text-xs leading-5 text-[var(--ink)]"
                    >
                      {message}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : null}
        </div>

        <div className="rounded-2xl border border-[var(--line)] bg-white p-6 shadow-[var(--shadow-card)]">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Leituras de progresso
          </p>
          <div className="mt-4 grid gap-3">
            {progressEntries.length > 0 ? (
              progressEntries.map(([key, value]) => (
                <div
                  key={key}
                  className="rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-4 py-3"
                >
                  <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">
                    {formatProgressLabel(key)}
                  </p>
                  <p className="mt-1 text-lg font-semibold tracking-[0.01em] text-[var(--ink)]">
                    {Array.isArray(value) ? value.length : String(value)}
                  </p>
                </div>
              ))
            ) : (
              <EmptyState
                title="Sem contadores ainda"
                description="Os campos de progresso aparecem conforme o backend avança pelas etapas do processo."
              />
            )}
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-[var(--line)] bg-white p-6 shadow-[var(--shadow-card)]">
        <div className="space-y-1">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Erros reportados
          </p>
          <h2 className="text-xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            Detalhes da execução
          </h2>
        </div>

        {progressErrors.length > 0 ? (
          <ul className="mt-4 space-y-3">
            {progressErrors.map((errorMessage, index) => (
              <li
                key={`${errorMessage}-${index}`}
                className="rounded-xl border border-[var(--warning-line)] bg-[var(--warning-bg)] px-4 py-3 text-sm text-[var(--warning)]"
              >
                {errorMessage}
              </li>
            ))}
          </ul>
        ) : (
          <div className="mt-4 rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-4 py-3 text-sm text-[var(--muted)]">
            Nenhum erro parcial reportado no campo <code>progresso.erros</code>.
          </div>
        )}
      </section>
    </div>
  );
}
