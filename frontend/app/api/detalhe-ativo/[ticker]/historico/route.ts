import { NextResponse } from "next/server";

import { ApiError, apiGet } from "@/lib/api";
import type { AssetHistoryPage } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ ticker: string }> },
) {
  const { ticker } = await context.params;
  const { searchParams } = new URL(request.url);
  const offset = searchParams.get("offset")?.trim() || "0";
  const limit = searchParams.get("limit")?.trim() || "10";

  try {
    const page = await apiGet<AssetHistoryPage>(
      `/ativos/${encodeURIComponent(ticker)}/historico?offset=${encodeURIComponent(offset)}&limit=${encodeURIComponent(limit)}`,
    );
    return NextResponse.json(page, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status, headers: { "Cache-Control": "no-store" } },
      );
    }

    return NextResponse.json(
      { error: "Falha ao buscar histórico do ativo." },
      { status: 500, headers: { "Cache-Control": "no-store" } },
    );
  }
}
