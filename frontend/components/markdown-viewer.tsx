"use client";

import { useState } from "react";

import { StatusBadge } from "@/components/status-badge";
import { formatDateTime } from "@/lib/format";
import type { MarkdownDocument } from "@/lib/types";

const markdownTypeLabel: Record<MarkdownDocument["tipo"], string> = {
  qualitativo: "qualitativo",
  analise_credito: "análise",
  delta_analise: "delta",
};

function DocumentMetaTag({
  label,
  tone = "default",
}: {
  label: string;
  tone?: "default" | "info";
}) {
  return (
    <span
      className={
        tone === "info"
          ? "inline-flex items-center border-l-2 border-l-[var(--info)] bg-[var(--info-bg)] px-2 py-1 font-mono text-[11px] leading-none uppercase tracking-[0.18em] text-[var(--info)]"
          : "inline-flex items-center border-l-2 border-l-[var(--warning)] bg-[var(--warning-bg)] px-2 py-1 font-mono text-[11px] leading-none uppercase tracking-[0.18em] text-[var(--warning)]"
      }
    >
      {label}
    </span>
  );
}

export function MarkdownViewer({
  documents,
}: {
  documents: MarkdownDocument[];
}) {
  const [selectedId, setSelectedId] = useState(documents[0]?.id ?? "");

  const selected =
    documents.find((document) => document.id === selectedId) ?? documents[0];

  return (
    <section className="grid gap-4 rounded-2xl border border-[var(--line)] bg-white p-6 shadow-[var(--shadow-card)] lg:h-[38rem] lg:grid-cols-[0.34fr_0.66fr]">
      <div className="space-y-3 lg:flex lg:min-h-0 lg:flex-col">
        <div className="space-y-1">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Markdowns
          </p>
          <h2 className="text-xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            Navegador de conteúdo
          </h2>
        </div>

        <div className="max-h-[32rem] space-y-2 overflow-auto pr-1 lg:min-h-0 lg:flex-1 lg:max-h-none">
          {documents.map((document) => {
            const active = document.id === selected?.id;

            return (
              <button
                key={document.id}
                type="button"
                onClick={() => setSelectedId(document.id)}
                className={`w-full rounded-2xl border px-4 py-3 text-left transition ${
                  active
                    ? "border-[var(--line-strong)] bg-[var(--panel)]"
                    : "border-[var(--line)] bg-white hover:border-[var(--line-strong)]"
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={markdownTypeLabel[document.tipo]} />
                  {document.financeiro ? (
                    <DocumentMetaTag label="financeiro" tone="info" />
                  ) : null}
                  <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">
                    {formatDateTime(document.criado_em)}
                  </span>
                </div>
                <p className="mt-2 text-sm font-medium text-[var(--ink)]">
                  {document.titulo}
                </p>
                {document.origem ? (
                  <p className="mt-1 text-xs text-[var(--muted)]">
                    Arquivo: {document.origem}
                  </p>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>

      <div className="max-h-[32rem] overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--panel)] lg:h-full lg:max-h-none lg:min-h-0">
        {selected ? (
          <div className="flex h-full min-h-0 flex-col">
            <div className="shrink-0 border-b border-[var(--line)] px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-medium text-[var(--ink)]">
                  {selected.titulo}
                </p>
                {selected.financeiro ? (
                  <DocumentMetaTag label="financeiro" tone="info" />
                ) : null}
              </div>
              <p className="mt-1 text-xs text-[var(--muted)]">
                {formatDateTime(selected.criado_em)}
              </p>
              {selected.origem ? (
                <p className="mt-1 text-xs text-[var(--muted)]">
                  Arquivo: {selected.origem}
                </p>
              ) : null}
            </div>
            <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap px-4 py-4 text-sm leading-7 text-[var(--ink)]">
              {selected.conteudo || "Markdown vazio."}
            </pre>
          </div>
        ) : (
          <div className="px-4 py-6 text-sm text-[var(--muted)]">
            Nenhum markdown disponível para este emissor.
          </div>
        )}
      </div>
    </section>
  );
}
