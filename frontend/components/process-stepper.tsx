import { computarEtapas, type EstadoEtapa } from "@/lib/process-monitor";
import type { ProcessRecord } from "@/lib/types";

const estiloDot: Record<EstadoEtapa, string> = {
  concluida: "border-[var(--accent)] bg-[var(--accent)] text-[var(--on-accent)]",
  pulada:
    "border-dashed border-[var(--line-strong)] bg-[var(--panel)] text-[var(--muted)]",
  atual:
    "border-[var(--accent)] bg-white text-[var(--accent)] ring-2 ring-[color-mix(in_srgb,var(--accent)_25%,transparent)] animate-pulse",
  falhou: "border-[var(--danger)] bg-[var(--danger)] text-white",
  pendente: "border-[var(--line)] bg-white text-[var(--muted)]",
};

const ETAPAS_COMPLETAS: EstadoEtapa[] = ["concluida", "pulada"];

function icone(estado: EstadoEtapa): string {
  if (estado === "concluida") {
    return "✓";
  }
  if (estado === "pulada") {
    return "–";
  }
  if (estado === "falhou") {
    return "✕";
  }
  if (estado === "atual") {
    return "●";
  }
  return "";
}

export function ProcessStepper({ process }: { process: ProcessRecord }) {
  const estacoes = computarEtapas(process);
  if (estacoes.length === 0) {
    return null;
  }

  return (
    <div className="mt-6 rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-4">
      <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
        Etapas
      </p>
      <ol className="mt-4 flex items-start">
        {estacoes.map((estacao, index) => {
          const primeiro = index === 0;
          const ultimo = index === estacoes.length - 1;
          const conectorEsquerda =
            !primeiro && ETAPAS_COMPLETAS.includes(estacoes[index - 1].estado);
          const conectorDireita = ETAPAS_COMPLETAS.includes(estacao.estado);

          return (
            <li
              key={estacao.key}
              className="flex flex-1 flex-col items-center"
              aria-label={`${estacao.rotulo}: ${estacao.estado}`}
            >
              <div className="flex w-full items-center">
                <span
                  className={`h-0.5 flex-1 ${primeiro ? "opacity-0" : conectorEsquerda ? "bg-[var(--accent)]" : "bg-[var(--line)]"}`}
                />
                <span
                  className={`flex h-7 w-7 items-center justify-center rounded-full border text-xs font-semibold ${estiloDot[estacao.estado]}`}
                >
                  {icone(estacao.estado)}
                </span>
                <span
                  className={`h-0.5 flex-1 ${ultimo ? "opacity-0" : conectorDireita ? "bg-[var(--accent)]" : "bg-[var(--line)]"}`}
                />
              </div>
              <span
                className={`mt-2 max-w-[8.5rem] text-center text-xs leading-tight text-balance ${estacao.estado === "atual" ? "font-semibold text-[var(--ink)]" : "text-[var(--muted)]"}`}
              >
                {estacao.rotulo}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
