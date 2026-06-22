import { NextResponse } from "next/server";

import { ApiError, apiGet } from "@/lib/api";
import type { AssetSearchOption } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const q = searchParams.get("q")?.trim() || "";
  const limit = searchParams.get("limit")?.trim() || "40";

  try {
    const options = await apiGet<AssetSearchOption[]>(
      `/ativos/opcoes?q=${encodeURIComponent(q)}&limit=${encodeURIComponent(limit)}`,
    );
    return NextResponse.json(options, {
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
      { error: "Falha ao buscar opções de ativos." },
      { status: 500, headers: { "Cache-Control": "no-store" } },
    );
  }
}
