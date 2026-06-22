function coerceNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function coerceDate(value: string | null | undefined): Date | null {
  if (!value) {
    return null;
  }

  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value: string | null | undefined): string {
  const date = coerceDate(value);
  if (!date) {
    return "—";
  }

  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeZone: "UTC",
  }).format(date);
}

export function formatDateTime(value: string | null | undefined): string {
  const date = coerceDate(value);
  if (!date) {
    return "—";
  }

  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

export function formatNumber(value: number | string | null | undefined): string {
  const parsed = coerceNumber(value);
  if (parsed === null) {
    return "—";
  }

  return new Intl.NumberFormat("pt-BR").format(parsed);
}

export function formatCurrency(value: number | string | null | undefined): string {
  const parsed = coerceNumber(value);
  if (parsed === null) {
    return "—";
  }

  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
    maximumFractionDigits: 0,
  }).format(parsed);
}

export function formatPercent(value: number | string | null | undefined): string {
  const parsed = coerceNumber(value);
  if (parsed === null) {
    return "—";
  }

  return new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(parsed) + "%";
}

export function formatBooleanFlag(value: boolean | string | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  if (typeof value === "boolean") {
    return value ? "Sim" : "Não";
  }

  const normalized = value.toString().trim().toLowerCase();
  if (["true", "sim", "s", "1"].includes(normalized)) {
    return "Sim";
  }
  if (["false", "nao", "não", "n", "0"].includes(normalized)) {
    return "Não";
  }

  return value;
}

export function formatText(value: string | null | undefined): string {
  return value?.trim() || "—";
}
