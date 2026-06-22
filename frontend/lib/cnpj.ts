export function normalizeCnpj(value: string): string {
  return value.replace(/\D/g, "").slice(0, 14);
}

export function normalizeIdentifier(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }

  if (/[a-z]/i.test(trimmed)) {
    return trimmed.toUpperCase();
  }

  const digits = normalizeCnpj(trimmed);
  return digits || trimmed.toUpperCase();
}

export function formatCnpj(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }

  const digits = normalizeCnpj(value);
  if (digits.length !== 14) {
    return value;
  }

  return digits.replace(
    /^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/,
    "$1.$2.$3/$4-$5",
  );
}

export function maskCnpj(value: string): string {
  const digits = normalizeCnpj(value);

  if (digits.length <= 2) return digits;
  if (digits.length <= 5) return digits.replace(/^(\d{2})(\d+)/, "$1.$2");
  if (digits.length <= 8) {
    return digits.replace(/^(\d{2})(\d{3})(\d+)/, "$1.$2.$3");
  }
  if (digits.length <= 12) {
    return digits.replace(/^(\d{2})(\d{3})(\d{3})(\d+)/, "$1.$2.$3/$4");
  }
  return digits.replace(
    /^(\d{2})(\d{3})(\d{3})(\d{4})(\d+)/,
    "$1.$2.$3/$4-$5",
  );
}
