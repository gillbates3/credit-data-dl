"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-3xl items-center justify-center px-4 py-12">
      <div className="w-full rounded-2xl border border-[var(--line)] bg-white p-8 shadow-[var(--shadow-card)]">
        <p className="font-mono text-xs uppercase tracking-[0.32em] text-[var(--muted)]">
          Falha de leitura
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-[0.01em] text-[var(--ink)]">
          Não foi possível carregar os dados agora.
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-7 text-[var(--muted)]">
          Isso pode acontecer quando a API está fora do ar, a conexão local falhou
          ou o backend respondeu com erro inesperado. Você pode tentar novamente
          sem sair da página.
        </p>
        <button
          type="button"
          onClick={reset}
          className="mt-6 inline-flex items-center justify-center rounded-full bg-[var(--accent)] px-5 py-2.5 text-sm font-medium text-[var(--on-accent)] transition hover:bg-[var(--accent-strong)]"
        >
          Tentar novamente
        </button>
      </div>
    </div>
  );
}
