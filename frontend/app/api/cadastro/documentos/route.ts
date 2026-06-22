import { NextResponse } from "next/server";

import { ApiError, apiGet, apiPostForm } from "@/lib/api";
import type { EmissorResolution, ProcessCreatedResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

async function resolveIdentifierToCnpj(identifier: string): Promise<string> {
  const resolution = await apiGet<EmissorResolution>(
    `/emissores/resolver/${encodeURIComponent(identifier)}`,
  );
  return resolution.cnpj;
}

export async function POST(request: Request) {
  try {
    const incoming = await request.formData();
    const identifier = incoming.get("identificador")?.toString().trim() || "";
    const files = incoming
      .getAll("arquivos")
      .filter((entry): entry is File => entry instanceof File && entry.size > 0);

    if (!identifier) {
      return NextResponse.json(
        { error: "Informe um ativo válido." },
        { status: 400 },
      );
    }

    if (files.length === 0) {
      return NextResponse.json(
        { error: "Envie pelo menos um PDF válido." },
        { status: 400 },
      );
    }

    const cnpj = await resolveIdentifierToCnpj(identifier);
    const payload = new FormData();
    payload.set("cnpj", cnpj);

    for (const file of files) {
      payload.append("arquivos", file, file.name);
    }

    const process = await apiPostForm<ProcessCreatedResponse>(
      "/cadastro/documentos",
      payload,
    );

    return NextResponse.json(process, {
      headers: {
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json(
        { error: error.message },
        {
          status: error.status,
          headers: {
            "Cache-Control": "no-store",
          },
        },
      );
    }

    return NextResponse.json(
      { error: "Não foi possível cadastrar os documentos agora." },
      {
        status: 500,
        headers: {
          "Cache-Control": "no-store",
        },
      },
    );
  }
}
