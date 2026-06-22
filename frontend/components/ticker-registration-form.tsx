"use client";

import { useActionState, useState } from "react";

import type { ActionState } from "@/app/cadastro-dados/actions";
import { SubmitButton } from "@/components/submit-button";

const initialState: ActionState = {};

interface TickerRegistrationFormProps {
  action: (state: ActionState, formData: FormData) => Promise<ActionState>;
}

export function TickerRegistrationForm({
  action,
}: TickerRegistrationFormProps) {
  const [state, formAction] = useActionState(action, initialState);
  const [deep, setDeep] = useState(false);

  return (
    <form
      action={formAction}
      className="space-y-4 rounded-2xl border border-[var(--line)] bg-white p-6 shadow-[var(--shadow-card)]"
    >
      <div className="space-y-1">
        <h2 className="text-xl font-semibold tracking-[0.01em] text-[var(--ink)]">
          Cadastro do ticker
        </h2>
        <p className="text-sm leading-7 text-[var(--muted)]">
          Dispara a pipeline para incluir ou atualizar um ativo a partir do ticker informado.
        </p>
      </div>

      <label className="block space-y-2">
        <span className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
          Ticker
        </span>
        <input
          name="ticker"
          required
          placeholder="PETR26"
          className="w-full rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-4 py-3 text-sm uppercase text-[var(--ink)] outline-none transition focus:border-[var(--line-strong)]"
        />
      </label>

      <label className="flex items-center gap-3 rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-4 py-3 text-sm text-[var(--ink)]">
        <input
          type="checkbox"
          name="deep"
          checked={deep}
          onChange={(event) => setDeep(event.target.checked)}
          className="h-4 w-4 rounded border-[var(--line-strong)] text-[var(--accent)] focus:ring-[var(--accent)]"
        />
        Rodar leitura profunda
      </label>

      {deep ? (
        <label className="block space-y-2">
          <span className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Data de corte do deep
          </span>
          <input
            type="date"
            name="data_corte_deep"
            className="w-full rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-4 py-3 text-sm text-[var(--ink)] outline-none transition focus:border-[var(--line-strong)]"
          />
        </label>
      ) : null}

      {state.error ? <p className="text-sm text-[var(--danger)]">{state.error}</p> : null}

      <SubmitButton
        idleLabel="Enviar ticker"
        pendingLabel="Criando processo..."
      />
    </form>
  );
}
