"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { normalizeCnpj } from "@/lib/cnpj";
import { cn } from "@/lib/utils";
import type { AssetSearchOption } from "@/lib/types";

type SelectorMode = "asset" | "issuer";

interface EntitySelectorComboboxProps {
  initialValue?: string;
  mode: SelectorMode;
}

function normalizeSearchText(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function getDirectIdentifier(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }

  const digits = normalizeCnpj(trimmed);
  if (digits.length === 14) {
    return digits;
  }

  const upper = trimmed.toUpperCase();
  if (/^[A-Z0-9./-]+$/.test(upper) && !/\s/.test(upper)) {
    return upper;
  }

  return "";
}

function OptionTypeLabel({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center border-l-2 border-l-[var(--line-strong)] bg-[var(--panel)] px-2 py-1 font-mono text-[11px] leading-none uppercase tracking-[0.18em] text-[var(--muted)]">
      {label}
    </span>
  );
}

export function EntitySelectorCombobox({
  initialValue = "",
  mode,
}: EntitySelectorComboboxProps) {
  const router = useRouter();
  const listboxId = useId();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [query, setQuery] = useState(initialValue);
  const [options, setOptions] = useState<AssetSearchOption[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const normalizedQuery = useMemo(
    () => normalizeSearchText(query),
    [query],
  );

  const ui = useMemo(
    () =>
      mode === "asset"
        ? {
            label: "Ativo ou emissor",
            placeholder: "Digite ticker, CNPJ ou nome do emissor",
            buttonLabel: "Abrir",
            helper:
              "Comece digitando para filtrar por ticker, CNPJ ou emissor, ou clique na seta para navegar pela lista completa em ordem alfabética.",
            emptyListLabel: "Lista completa de ativos e emissores",
            loadingSearch: "Pesquisando alternativas...",
            loadingAll: "Carregando ativos cadastrados...",
            emptySearch:
              "Nenhuma alternativa encontrada para o que foi digitado.",
            emptyAll:
              "Nenhum ativo ou emissor cadastrado foi encontrado para a lista completa.",
            invalidSelection:
              "Informe um ticker, CNPJ ou nome do emissor para pesquisar.",
          }
        : {
            label: "CNPJ, ativo ou emissor",
            placeholder: "Digite CNPJ, ticker ou nome do emissor",
            buttonLabel: "Abrir emissor",
            helper:
              "Digite um CNPJ, ticker ou nome do emissor para abrir a visão consolidada, ou use a seta para navegar pela lista disponível.",
            emptyListLabel: "Lista completa de emissores e ativos",
            loadingSearch: "Pesquisando emissores...",
            loadingAll: "Carregando emissores cadastrados...",
            emptySearch:
              "Nenhum emissor compatível foi encontrado para o que foi digitado.",
            emptyAll:
              "Nenhum emissor ou ativo cadastrado foi encontrado para a lista completa.",
            invalidSelection:
              "Informe um CNPJ, ticker ou nome do emissor para pesquisar.",
          },
    [mode],
  );

  async function fetchOptions(search: string) {
    const trimmedSearch = search.trim();
    const response = await fetch(
      `/api/detalhe-ativo/opcoes?q=${encodeURIComponent(trimmedSearch)}&limit=${trimmedSearch ? "24" : "200"}`,
      { cache: "no-store" },
    );
    const payload = (await response.json().catch(() => null)) as
      | AssetSearchOption[]
      | { error?: string }
      | null;

    if (!response.ok) {
      throw new Error(payload && "error" in payload ? payload.error : "Falha na busca.");
    }

    return Array.isArray(payload) ? payload : [];
  }

  function scoreOption(option: AssetSearchOption, search: string): number {
    const searchText = normalizeSearchText(search);
    if (!searchText) {
      return mode === "asset"
        ? option.tipo === "ativo"
          ? 10
          : 0
        : option.tipo === "emissor"
          ? 10
          : 0;
    }

    const primary = normalizeSearchText(option.primary);
    const secondary = normalizeSearchText(option.secondary);
    const value = normalizeSearchText(option.value);
    let score = 0;

    if (primary === searchText) score += 120;
    if (value === searchText) score += 115;
    if (secondary === searchText) score += 105;
    if (primary.startsWith(searchText)) score += 90;
    if (value.startsWith(searchText)) score += 82;
    if (secondary.startsWith(searchText)) score += 74;
    if (primary.includes(searchText)) score += 64;
    if (secondary.includes(searchText)) score += 52;
    if (value.includes(searchText)) score += 44;
    if (mode === "asset" && option.tipo === "ativo") score += 8;
    if (mode === "issuer" && option.tipo === "emissor") score += 8;

    return score;
  }

  function getBestOption(
    availableOptions: AssetSearchOption[],
    search: string,
  ): AssetSearchOption | null {
    if (availableOptions.length === 0) {
      return null;
    }

    return [...availableOptions]
      .sort((left, right) => scoreOption(right, search) - scoreOption(left, search))
      .at(0) ?? null;
  }

  function openSelection(value: string) {
    const target = value.trim();
    if (!target) {
      setError(ui.invalidSelection);
      return;
    }

    setQuery(target);
    setError(null);
    setIsOpen(false);

    if (mode === "asset") {
      router.push(`/detalhe-ativo?identificador=${encodeURIComponent(target)}`);
      return;
    }

    router.push(`/detalhe-emissor/${encodeURIComponent(target)}`);
  }

  async function resolveAndOpen(rawValue: string) {
    const trimmedValue = rawValue.trim();
    if (!trimmedValue) {
      setError(ui.invalidSelection);
      return;
    }

    setIsLoading(true);

    try {
      const fetchedOptions = await fetchOptions(trimmedValue);
      setOptions(fetchedOptions);

      const bestOption = getBestOption(fetchedOptions, trimmedValue);
      if (bestOption) {
        openSelection(bestOption.value);
        return;
      }

      const directIdentifier = getDirectIdentifier(trimmedValue);
      if (directIdentifier) {
        openSelection(directIdentifier);
        return;
      }

      setError(ui.invalidSelection);
    } catch (fetchError) {
      setOptions([]);
      setError(
        fetchError instanceof Error
          ? fetchError.message
          : "Não foi possível pesquisar os ativos.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const trimmedQuery = query.trim();
    const timeoutId = window.setTimeout(async () => {
      setIsLoading(true);
      try {
        const fetchedOptions = await fetchOptions(trimmedQuery);
        setOptions(fetchedOptions);
      } catch (fetchError) {
        setOptions([]);
        setError(
          fetchError instanceof Error
            ? fetchError.message
            : "Não foi possível pesquisar os ativos.",
        );
      } finally {
        setIsLoading(false);
      }
    }, trimmedQuery ? 160 : 0);

    return () => window.clearTimeout(timeoutId);
  }, [isOpen, query]);

  useEffect(() => {
    function handlePointerDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    window.addEventListener("mousedown", handlePointerDown);
    return () => window.removeEventListener("mousedown", handlePointerDown);
  }, []);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void resolveAndOpen(query);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-2xl border border-[var(--line)] bg-white p-6 shadow-[var(--shadow-card)]"
    >
      <div className="space-y-2">
        <label
          htmlFor={listboxId}
          className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--muted)]"
        >
          {ui.label}
        </label>
        <div ref={containerRef} className="relative">
          <input
            id={listboxId}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              if (error) setError(null);
              setIsOpen(true);
            }}
            onFocus={() => {
              setIsOpen(true);
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setIsOpen(false);
              }
            }}
            placeholder={ui.placeholder}
            autoComplete="off"
            className="w-full rounded-2xl border border-[var(--line)] bg-[var(--panel)] px-4 py-3 pr-48 text-sm text-[var(--ink)] outline-none transition focus:border-[var(--line-strong)] md:pr-52"
          />
          <button
            type="button"
            onClick={() => {
              setIsOpen((current) => !current);
              if (error) setError(null);
            }}
            aria-label={isOpen ? "Fechar lista de opções" : "Mostrar lista de opções"}
            className="absolute right-24 top-2 inline-flex h-10 w-10 items-center justify-center rounded-full border border-[var(--line)] bg-white text-base text-[var(--muted)] transition hover:border-[var(--line-strong)] hover:bg-[var(--panel)] hover:text-[var(--ink)] md:right-28"
          >
            ▾
          </button>
          <button
            type="submit"
            className="absolute right-2 top-2 inline-flex h-10 min-w-[6rem] items-center justify-center rounded-full bg-[var(--accent)] px-4 text-sm font-medium text-[var(--on-accent)] transition hover:bg-[var(--accent-strong)]"
          >
            {ui.buttonLabel}
          </button>

          {isOpen || isLoading ? (
            <div className="absolute left-0 right-0 top-[calc(100%+0.5rem)] z-20 overflow-hidden rounded-xl border border-[var(--line)] bg-white shadow-[var(--shadow-card)]">
              {!query.trim() ? (
                <div className="border-b border-[var(--line)] bg-[var(--panel)] px-4 py-2.5 text-[11px] font-medium uppercase tracking-[0.2em] text-[var(--muted)]">
                  {ui.emptyListLabel}
                </div>
              ) : null}
              {isLoading ? (
                <div className="px-4 py-3 text-sm text-[var(--muted)]">
                  {query.trim() ? ui.loadingSearch : ui.loadingAll}
                </div>
              ) : options.length > 0 ? (
                <ul role="listbox" className="max-h-72 overflow-y-auto py-2">
                  {options.map((option) => (
                    <li key={option.id}>
                      <button
                        type="button"
                        onClick={() => openSelection(option.value)}
                        className={cn(
                          "flex w-full items-start justify-between gap-4 border-l-[3px] border-transparent px-4 py-3 text-left transition hover:border-l-[var(--accent)] hover:bg-[rgba(10,35,0,0.10)] hover:shadow-[inset_0_1px_0_rgba(10,35,0,0.06)]",
                          normalizedQuery === normalizeSearchText(option.value) &&
                            "border-l-[var(--accent)] bg-[rgba(10,35,0,0.14)] shadow-[inset_0_1px_0_rgba(10,35,0,0.08)]",
                        )}
                      >
                        <div>
                          <p className="text-sm font-medium text-[var(--ink)]">
                            {option.primary}
                          </p>
                          <p className="mt-1 text-xs text-[var(--muted)]">
                            {option.secondary}
                          </p>
                        </div>
                        <OptionTypeLabel label={option.tipo} />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="px-4 py-3 text-sm text-[var(--muted)]">
                  {query.trim() ? ui.emptySearch : ui.emptyAll}
                </div>
              )}
            </div>
          ) : null}
        </div>
      </div>

      <p className="mt-3 text-sm text-[var(--muted)]">{ui.helper}</p>
      {error ? <p className="mt-2 text-sm text-[var(--danger)]">{error}</p> : null}
    </form>
  );
}
