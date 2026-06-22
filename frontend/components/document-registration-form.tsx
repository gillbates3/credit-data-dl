"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import type { ProcessCreatedResponse } from "@/lib/types";

interface DocumentRegistrationFormProps {
  assetOptions: Array<{
    value: string;
    label: string;
  }>;
}

export function DocumentRegistrationForm({
  assetOptions,
}: DocumentRegistrationFormProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const form = event.currentTarget;
    const payload = new FormData(form);

    setError(null);
    setIsSubmitting(true);

    void (async () => {
      try {
        const response = await fetch("/api/cadastro/documentos", {
          method: "POST",
          body: payload,
        });

        const body = (await response.json().catch(() => null)) as
          | ProcessCreatedResponse
          | { error?: string }
          | null;

        if (!response.ok) {
          throw new Error(body && "error" in body ? body.error : "Falha no envio.");
        }

        const processId =
          body && "process_id" in body ? body.process_id : null;

        if (!processId) {
          throw new Error("A resposta não trouxe o identificador do processo.");
        }

        form.reset();
        router.push(
          `/cadastro-dados?processo=${encodeURIComponent(processId)}`,
        );
        router.refresh();
      } catch (submissionError) {
        setError(
          submissionError instanceof Error
            ? submissionError.message
            : "Não foi possível cadastrar os documentos.",
        );
      } finally {
        setIsSubmitting(false);
      }
    })();
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-4 rounded-2xl border border-[var(--line)] bg-white p-6 shadow-[var(--shadow-card)]"
    >
      <div className="space-y-1">
        <h2 className="text-xl font-semibold tracking-[0.01em] text-[var(--ink)]">
          Cadastro de documentos
        </h2>
        <p className="text-sm leading-7 text-[var(--muted)]">
          Selecione um ativo já cadastrado e envie um ou mais PDFs para processamento quantitativo e qualitativo.
        </p>
      </div>

      <label className="block space-y-2">
        <span className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
          Ativo cadastrado
        </span>
        <select
          name="identificador"
          required
          defaultValue=""
          disabled={assetOptions.length === 0}
          className="w-full rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-4 py-3 text-sm text-[var(--ink)] outline-none transition focus:border-[var(--line-strong)]"
        >
          <option value="" disabled>
            {assetOptions.length > 0
              ? "Selecione um ticker já cadastrado"
              : "Nenhum ativo cadastrado ainda"}
          </option>
          {assetOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      {assetOptions.length === 0 ? (
        <p className="text-sm text-[var(--muted)]">
          Cadastre primeiro um ticker para habilitar o envio de documentos.
        </p>
      ) : null}

      <label className="block space-y-2">
        <span className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
          PDFs
        </span>
        <input
          name="arquivos"
          type="file"
          multiple
          accept="application/pdf"
          required
          disabled={isSubmitting}
          className="block w-full rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-4 py-3 text-sm text-[var(--ink)] file:mr-4 file:rounded-full file:border-0 file:bg-[var(--accent)] file:px-4 file:py-2 file:text-sm file:font-medium file:text-[var(--on-accent)] hover:file:bg-[var(--accent-strong)]"
        />
      </label>

      {error ? <p className="text-sm text-[var(--danger)]">{error}</p> : null}

      <button
        type="submit"
        disabled={assetOptions.length === 0 || isSubmitting}
        className="inline-flex items-center justify-center gap-2 rounded-full bg-[var(--accent)] px-4 py-2.5 text-sm font-medium text-[var(--on-accent)] transition hover:bg-[var(--accent-strong)] disabled:cursor-not-allowed disabled:opacity-70"
      >
        {isSubmitting ? (
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-[rgba(255,240,220,0.35)] border-t-[var(--on-accent)]" />
        ) : null}
        {isSubmitting ? "Subindo arquivos..." : "Enviar documentos"}
      </button>
    </form>
  );
}
