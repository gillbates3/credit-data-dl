import "server-only";

const BASE = process.env.API_BASE_URL;
const KEY = process.env.API_KEY;

function getRequiredEnv(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(`Variavel de ambiente ausente: ${name}.`);
  }
  return value;
}

function buildUrl(path: string): string {
  const base = getRequiredEnv("API_BASE_URL", BASE);
  return `${base}${path}`;
}

async function readErrorMessage(response: Response): Promise<string> {
  const raw = await response.text();
  if (!raw) {
    return `Erro HTTP ${response.status}.`;
  }

  try {
    const parsed = JSON.parse(raw) as { detail?: string; error?: string };
    if (typeof parsed.detail === "string" && parsed.detail) {
      return parsed.detail;
    }
    if (typeof parsed.error === "string" && parsed.error) {
      return parsed.error;
    }
  } catch {
    // Se nao for JSON, usa o corpo cru.
  }

  return raw;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiGetOptions {
  /**
   * Segundos de cache no Data Cache do Next (revalidação em background).
   * Omitido => `cache: "no-store"` (sempre fresco). Use para leituras que não
   * mudam a cada segundo, deixando a troca de aba instantânea ao revisitar.
   */
  revalidate?: number;
}

export async function apiGet<T>(
  path: string,
  options?: ApiGetOptions,
): Promise<T> {
  const cacheInit =
    options?.revalidate !== undefined
      ? { next: { revalidate: options.revalidate } }
      : { cache: "no-store" as const };

  const response = await fetch(buildUrl(path), {
    headers: {
      "X-API-Key": getRequiredEnv("API_KEY", KEY),
    },
    ...cacheInit,
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  return response.json() as Promise<T>;
}

export async function apiPostJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(buildUrl(path), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": getRequiredEnv("API_KEY", KEY),
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  return response.json() as Promise<T>;
}

export async function apiPostForm<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(buildUrl(path), {
    method: "POST",
    headers: {
      "X-API-Key": getRequiredEnv("API_KEY", KEY),
    },
    body: form,
    cache: "no-store",
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  return response.json() as Promise<T>;
}
