"use client";

import { useDeferredValue, useMemo, useState } from "react";

import {
  formatDate,
  formatNumber,
  formatText,
} from "@/lib/format";
import type { FinancialStatementRow } from "@/lib/types";

interface FinancialStatementsTableProps {
  rows: FinancialStatementRow[];
}

export function FinancialStatementsTable({
  rows,
}: FinancialStatementsTableProps) {
  const [query, setQuery] = useState("");
  const [statementType, setStatementType] = useState("todos");
  const deferredQuery = useDeferredValue(query);

  const availableTypes = useMemo(
    () => Array.from(new Set(rows.map((row) => row.demonstracao))).sort(),
    [rows],
  );

  const filteredRows = useMemo(() => {
    const normalizedQuery = deferredQuery.trim().toLowerCase();

    return rows.filter((row) => {
      const matchesType =
        statementType === "todos" || row.demonstracao === statementType;
      if (!matchesType) {
        return false;
      }

      if (!normalizedQuery) {
        return true;
      }

      const haystack = [
        row.cd_conta,
        row.ds_conta,
        row.demonstracao,
        row.tipo_doc,
        row.data_ref,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return haystack.includes(normalizedQuery);
    });
  }, [deferredQuery, rows, statementType]);

  return (
    <section className="space-y-4 rounded-2xl border border-[var(--line)] bg-white p-6 shadow-[var(--shadow-card)]">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-1">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]">
            Dados financeiros
          </p>
          <h2 className="text-xl font-semibold tracking-[0.01em] text-[var(--ink)]">
            Demonstrações em formato de tabela
          </h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-2">
            <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">
              Buscar conta
            </span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Conta, código ou período"
              className="w-full rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-4 py-2.5 text-sm text-[var(--ink)] outline-none transition focus:border-[var(--line-strong)]"
            />
          </label>
          <label className="space-y-2">
            <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">
              Demonstração
            </span>
            <select
              value={statementType}
              onChange={(event) => setStatementType(event.target.value)}
              className="w-full rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-4 py-2.5 text-sm text-[var(--ink)] outline-none transition focus:border-[var(--line-strong)]"
            >
              <option value="todos">Todas</option>
              {availableTypes.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-4 py-3 text-sm text-[var(--muted)]">
        {filteredRows.length} linha(s) exibida(s) de {rows.length} total.
      </div>

      <div className="overflow-hidden rounded-xl border border-[var(--line)]">
        <div className="max-h-[34rem] overflow-auto">
          <table className="min-w-full border-separate border-spacing-0 bg-white">
            <thead className="sticky top-0 bg-[var(--panel)]">
              <tr>
                {["Data ref", "Tipo", "Demonstração", "Conta", "Descrição", "Valor"].map(
                  (header) => (
                    <th
                      key={header}
                      className="border-b border-[var(--line)] px-4 py-3 text-left font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]"
                    >
                      {header}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((row) => (
                <tr key={row.id}>
                  <td className="border-b border-[var(--line)] px-4 py-3 text-sm text-[var(--ink)]">
                    {formatDate(row.data_ref)}
                  </td>
                  <td className="border-b border-[var(--line)] px-4 py-3 text-sm text-[var(--ink)]">
                    {row.tipo_doc}
                  </td>
                  <td className="border-b border-[var(--line)] px-4 py-3 text-sm text-[var(--ink)]">
                    {row.demonstracao}
                  </td>
                  <td className="border-b border-[var(--line)] px-4 py-3 font-mono text-xs text-[var(--ink)]">
                    {row.cd_conta}
                  </td>
                  <td className="border-b border-[var(--line)] px-4 py-3 text-sm text-[var(--ink)]">
                    {formatText(row.ds_conta)}
                  </td>
                  <td className="border-b border-[var(--line)] px-4 py-3 text-right text-sm text-[var(--ink)]">
                    {formatNumber(row.valor)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
