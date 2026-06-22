"use server";

import { redirect } from "next/navigation";

import { ApiError, apiPostJson } from "@/lib/api";
import type { ProcessCreatedResponse } from "@/lib/types";

export interface ActionState {
  error?: string;
}

export async function registerTickerAction(
  _state: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const ticker = formData.get("ticker")?.toString().trim().toUpperCase();
  const deep = formData.get("deep") === "on";
  const dataCorteDeep = formData.get("data_corte_deep")?.toString().trim() || null;

  if (!ticker) {
    return { error: "Informe um ticker válido." };
  }

  let response: ProcessCreatedResponse;

  try {
    response = await apiPostJson<ProcessCreatedResponse>("/cadastro/ticker", {
      ticker,
      deep,
      data_corte_deep: deep ? dataCorteDeep : null,
    });
  } catch (error) {
    if (error instanceof ApiError) {
      return { error: error.message };
    }

    return { error: "Não foi possível criar o processo de cadastro por ticker." };
  }

  redirect(
    `/cadastro-dados?processo=${encodeURIComponent(response.process_id)}`,
  );
}
