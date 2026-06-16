"""
Camada de dados V2 para o pipeline de credito.

Este modulo e a unica fronteira que conhece o Supabase. Ele expoe funcoes
sincronas de leitura e escrita para serem chamadas pelo orquestrador via
`asyncio.to_thread(...)` no futuro.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
from supabase import Client, create_client

SCRIPT_DIR = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
ENV_LOCAL_FILE = PROJETO_RAIZ / ".env.local"
ENV_FILE = PROJETO_RAIZ / ".env"

BATCH_SIZE = 500

_CLIENT: Client | None = None
_ENV_LOADED = False


def normaliza_cnpj(cnpj: str | None) -> str:
    return re.sub(r"\D", "", cnpj or "")


def _batches(lst: list[dict[str, Any]], n: int) -> Iterable[list[dict[str, Any]]]:
    for idx in range(0, len(lst), n):
        yield lst[idx : idx + n]


def _load_env_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    load_dotenv(ENV_LOCAL_FILE)
    load_dotenv(ENV_FILE)
    _ENV_LOADED = True


def _get_client() -> Client:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    _load_env_once()
    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_KEY") or "").strip()
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL e SUPABASE_KEY nao foram encontrados. "
            "Verifique .env.local e .env."
        )

    _CLIENT = create_client(url, key)
    return _CLIENT


def _first_or_none(rows: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    if not rows:
        return None
    return rows[0]


def _date_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value[:10]
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()[:10]
    return str(value)[:10]


def _select_rows(
    table_name: str,
    select_cols: str,
    filter_col: str,
    filter_value: str,
) -> list[dict[str, Any]]:
    response = (
        _get_client()
        .table(table_name)
        .select(select_cols)
        .eq(filter_col, filter_value)
        .execute()
    )
    return response.data or []


def buscar_emissor(cnpj: str) -> dict[str, Any] | None:
    cnpj_norm = normaliza_cnpj(cnpj)
    if not cnpj_norm:
        return None
    return _first_or_none(_select_rows("emissores", "*", "cnpj", cnpj_norm))


def buscar_hashes_qualitativo(cnpj: str) -> set[str]:
    cnpj_norm = normaliza_cnpj(cnpj)
    if not cnpj_norm:
        return set()
    rows = _select_rows(
        "emissor_compendio_qualitativo",
        "hash_md5",
        "cnpj",
        cnpj_norm,
    )
    return {row["hash_md5"] for row in rows if row.get("hash_md5")}


def buscar_hashes_quantitativo(cnpj: str) -> set[str]:
    cnpj_norm = normaliza_cnpj(cnpj)
    if not cnpj_norm:
        return set()
    rows = _select_rows(
        "emissor_compendio_quantitativo",
        "hash_md5",
        "cnpj",
        cnpj_norm,
    )
    return {row["hash_md5"] for row in rows if row.get("hash_md5")}


def buscar_periodos_demonstracoes(cnpj: str) -> set[str]:
    cnpj_norm = normaliza_cnpj(cnpj)
    if not cnpj_norm:
        return set()
    rows = _select_rows(
        "demonstracoes_financeiras",
        "data_ref",
        "cnpj",
        cnpj_norm,
    )
    return {data_ref for row in rows if (data_ref := _date_str(row.get("data_ref")))}


def buscar_datas_historico(ticker_deb: str) -> set[str]:
    ticker = (ticker_deb or "").strip().upper()
    if not ticker:
        return set()
    rows = _select_rows(
        "deb_historico_diario",
        "data_referencia",
        "ticker_deb",
        ticker,
    )
    return {
        data_ref
        for row in rows
        if (data_ref := _date_str(row.get("data_referencia")))
    }


def buscar_ultima_analise(cnpj: str) -> dict[str, Any] | None:
    cnpj_norm = normaliza_cnpj(cnpj)
    if not cnpj_norm:
        return None
    rows = _select_rows("v_ultima_analise_credito", "*", "cnpj", cnpj_norm)
    return _first_or_none(rows)


def montar_demonstracoes_estruturadas(cnpj: str) -> dict[str, Any]:
    cnpj_norm = normaliza_cnpj(cnpj)
    periodos: dict[str, dict[str, Any]] = {}

    if not cnpj_norm:
        return {"cnpj": "", "periodos": {}}

    rows = _select_rows(
        "demonstracoes_financeiras",
        "data_ref,tipo_doc,demonstracao,cd_conta,ds_conta,valor",
        "cnpj",
        cnpj_norm,
    )
    emissor = buscar_emissor(cnpj_norm)

    for row in rows:
        data_ref = _date_str(row.get("data_ref"))
        if not data_ref:
            continue

        tipo_doc = row.get("tipo_doc")
        demonstracao = row.get("demonstracao")
        cd_conta = str(row.get("cd_conta") or "").strip()
        if not tipo_doc or not demonstracao or not cd_conta:
            continue

        # Premissa: cada data_ref tem um unico tipo_doc (fechamento anual = DFP,
        # trimestral = ITR). Se um mesmo data_ref tiver DFP e ITR, o primeiro tipo
        # vence e as demonstracoes se mesclam - aceitavel para o read-model do Passo 6.
        periodo = periodos.setdefault(
            data_ref,
            {
                "tipo": tipo_doc,
                "demonstracoes": {},
            },
        )
        if not periodo.get("tipo"):
            periodo["tipo"] = tipo_doc

        contas = periodo["demonstracoes"].setdefault(demonstracao, {})
        contas[cd_conta] = {
            "cd_conta": cd_conta,
            "ds_conta": row.get("ds_conta"),
            "valor": row.get("valor"),
        }

    resultado: dict[str, Any] = {
        "cnpj": cnpj_norm,
        "periodos": periodos,
    }
    if emissor and emissor.get("cod_cvm"):
        resultado["cod_cvm"] = emissor["cod_cvm"]
    return resultado


def salvar_emissor(identidade: dict[str, Any]) -> None:
    cnpj = normaliza_cnpj(identidade.get("cnpj_emissor"))
    nome = identidade.get("nome_emissor")
    if not cnpj:
        raise ValueError("identidade sem cnpj_emissor")
    if not nome:
        raise ValueError("identidade sem nome_emissor")

    registro = {
        "cnpj": cnpj,
        "nome": nome,
        "cod_cvm": identidade.get("cod_cvm"),
        "categoria_cvm": identidade.get("categoria_cvm"),
        "tipo_capital": identidade.get("tipo_capital"),
    }
    _get_client().table("emissores").upsert(registro, on_conflict="cnpj").execute()


def salvar_caracteristicas(
    cnpj: str,
    ticker_deb: str,
    caracteristicas: dict[str, Any],
) -> None:
    cnpj_norm = normaliza_cnpj(cnpj)
    ticker = (ticker_deb or "").strip().upper()
    if not cnpj_norm or not ticker:
        raise ValueError("cnpj e ticker_deb sao obrigatorios")

    registro = dict(caracteristicas or {})
    registro["cnpj"] = cnpj_norm
    registro["ticker_deb"] = ticker
    _get_client().table("deb_caracteristicas").upsert(
        registro,
        on_conflict="ticker_deb",
    ).execute()


def salvar_agenda(cnpj: str, ticker_deb: str, agenda: list[dict[str, Any]]) -> int:
    cnpj_norm = normaliza_cnpj(cnpj)
    ticker = (ticker_deb or "").strip().upper()
    if not cnpj_norm or not ticker:
        raise ValueError("cnpj e ticker_deb sao obrigatorios")
    if not agenda:
        return 0

    registros = []
    for item in agenda:
        registro = dict(item or {})
        registro["cnpj"] = cnpj_norm
        registro["ticker_deb"] = ticker
        registros.append(registro)

    for lote in _batches(registros, BATCH_SIZE):
        _get_client().table("deb_agenda").upsert(
            lote,
            on_conflict="ticker_deb,data_evento,evento,data_base",
        ).execute()
    return len(registros)


def salvar_historico(ticker_deb: str, historico: list[dict[str, Any]]) -> int:
    ticker = (ticker_deb or "").strip().upper()
    if not ticker:
        raise ValueError("ticker_deb e obrigatorio")
    if not historico:
        return 0

    registros = []
    for item in historico:
        registro = dict(item or {})
        registro["ticker_deb"] = ticker
        registros.append(registro)

    for lote in _batches(registros, BATCH_SIZE):
        _get_client().table("deb_historico_diario").upsert(
            lote,
            on_conflict="ticker_deb,data_referencia",
        ).execute()
    return len(registros)


def periodos_para_linhas(cnpj: str, resultado: dict[str, Any]) -> list[dict[str, Any]]:
    cnpj_norm = normaliza_cnpj(cnpj)
    if not cnpj_norm:
        raise ValueError("cnpj e obrigatorio")

    linhas: list[dict[str, Any]] = []
    periodos = (resultado or {}).get("periodos") or {}
    for data_ref, dados_periodo in periodos.items():
        tipo_doc = (dados_periodo or {}).get("tipo")
        demonstracoes = (dados_periodo or {}).get("demonstracoes") or {}
        if not tipo_doc:
            continue

        for demonstracao, contas in demonstracoes.items():
            if not isinstance(contas, dict):
                continue
            for cd_chave, conta in contas.items():
                conta = conta or {}
                cd_conta = str(conta.get("cd_conta") or cd_chave or "").strip()
                if not cd_conta:
                    continue
                linhas.append(
                    {
                        "cnpj": cnpj_norm,
                        "data_ref": data_ref,
                        "tipo_doc": tipo_doc,
                        "demonstracao": demonstracao,
                        "cd_conta": cd_conta,
                        "ds_conta": conta.get("ds_conta"),
                        "valor": conta.get("valor"),
                    }
                )
    return linhas


def salvar_demonstracoes(linhas: list[dict[str, Any]]) -> int:
    if not linhas:
        return 0

    for lote in _batches(linhas, BATCH_SIZE):
        _get_client().table("demonstracoes_financeiras").upsert(
            lote,
            on_conflict="cnpj,data_ref,tipo_doc,demonstracao,cd_conta",
        ).execute()
    return len(linhas)


def salvar_compendio_qualitativo(
    cnpj: str,
    nome_arquivo: str,
    hash_md5: str,
    markdown: str,
    force: bool = False,
) -> None:
    cnpj_norm = normaliza_cnpj(cnpj)
    if not cnpj_norm or not nome_arquivo or not hash_md5:
        raise ValueError("cnpj, nome_arquivo e hash_md5 sao obrigatorios")

    registro = {
        "cnpj": cnpj_norm,
        "nome_arquivo": nome_arquivo,
        "hash_md5": hash_md5,
        "markdown_conteudo": markdown,
    }
    _get_client().table("emissor_compendio_qualitativo").upsert(
        registro,
        on_conflict="cnpj,hash_md5",
        ignore_duplicates=not force,
    ).execute()


def salvar_compendio_quantitativo(
    cnpj: str,
    nome_arquivo: str,
    hash_md5: str,
    force: bool = False,
) -> None:
    cnpj_norm = normaliza_cnpj(cnpj)
    if not cnpj_norm or not nome_arquivo or not hash_md5:
        raise ValueError("cnpj, nome_arquivo e hash_md5 sao obrigatorios")

    # O manifesto quantitativo deve ser gravado apenas depois de salvar as
    # demonstracoes. Se houver falha antes disso, a proxima execucao reprocessa
    # o PDF e o upsert das demonstracoes continua idempotente.
    registro = {
        "cnpj": cnpj_norm,
        "nome_arquivo": nome_arquivo,
        "hash_md5": hash_md5,
    }
    _get_client().table("emissor_compendio_quantitativo").upsert(
        registro,
        on_conflict="cnpj,hash_md5",
        ignore_duplicates=not force,
    ).execute()


def salvar_analise_credito(
    cnpj: str,
    analise_markdown: str,
    delta_markdown: str | None,
    metadados: dict[str, Any] | None,
) -> None:
    cnpj_norm = normaliza_cnpj(cnpj)
    if not cnpj_norm:
        raise ValueError("cnpj e obrigatorio")
    if not analise_markdown:
        raise ValueError("analise_markdown e obrigatorio")

    registro = {
        "cnpj": cnpj_norm,
        "analise_markdown": analise_markdown,
        "delta_markdown": delta_markdown,
        "metadados": metadados,
    }
    _get_client().table("emissor_analise_credito").insert(registro).execute()


def criar_job(tipo: str, alvo: str) -> str:
    tipo_norm = (tipo or "").strip().lower()
    if tipo_norm not in {"ingestao", "analise"}:
        raise ValueError("tipo deve ser 'ingestao' ou 'analise'")
    alvo_norm = (alvo or "").strip()
    if not alvo_norm:
        raise ValueError("alvo e obrigatorio")

    job_id = str(uuid.uuid4())
    registro = {
        "id": job_id,
        "tipo": tipo_norm,
        "alvo": alvo_norm,
        "status": "pendente",
    }
    _get_client().table("pipeline_jobs").insert(registro).execute()
    return job_id


def atualizar_job(
    job_id: str,
    *,
    status: str | None = None,
    etapa_atual: str | None = None,
    progresso: dict[str, Any] | list[Any] | None = None,
    erro: str | None = None,
) -> None:
    if not job_id:
        raise ValueError("job_id e obrigatorio")

    payload: dict[str, Any] = {}
    if status is not None:
        payload["status"] = status
    if etapa_atual is not None:
        payload["etapa_atual"] = etapa_atual
    if progresso is not None:
        payload["progresso"] = progresso
    if erro is not None:
        payload["erro"] = erro
    if not payload:
        return

    _get_client().table("pipeline_jobs").update(payload).eq("id", job_id).execute()


def buscar_job(job_id: str) -> dict[str, Any] | None:
    if not job_id:
        return None
    rows = _select_rows("pipeline_jobs", "*", "id", job_id)
    return _first_or_none(rows)


def listar_jobs_recentes() -> list[dict[str, Any]]:
    """Ultimos 100 jobs (view v_jobs_recentes, ja ordenada/limitada)."""
    return _get_client().table("v_jobs_recentes").select("*").execute().data or []


def listar_portfolio() -> list[dict[str, Any]]:
    """Portfolio de operacoes ativas (view v_portfolio_ativo)."""
    return _get_client().table("v_portfolio_ativo").select("*").execute().data or []


def listar_proximos_pagamentos() -> list[dict[str, Any]]:
    """Proximos eventos de pagamento (view v_proximos_pagamentos)."""
    return (
        _get_client().table("v_proximos_pagamentos").select("*").execute().data or []
    )


def listar_debentures_emissor(cnpj: str) -> list[dict[str, Any]]:
    """Debentures de um emissor (view v_emissor_debentures, filtrada por cnpj)."""
    cnpj_norm = normaliza_cnpj(cnpj)
    if not cnpj_norm:
        return []
    return (
        _get_client()
        .table("v_emissor_debentures")
        .select("*")
        .eq("cnpj", cnpj_norm)
        .execute()
        .data
        or []
    )


def _smoke_test() -> None:
    print("=" * 72)
    print("SMOKE TEST - SERVICO_REPOSITORIO")
    print("=" * 72)

    _get_client()
    print("[ok] Conexao Supabase criada.")

    job_id = criar_job("ingestao", "TESTE11")
    atualizar_job(job_id, status="rodando", etapa_atual="identidade")
    job = buscar_job(job_id)
    assert job is not None and job["status"] == "rodando"
    assert job["etapa_atual"] == "identidade"
    print(f"[ok] pipeline_jobs funcionando para job_id={job_id}")

    cnpj_teste = f"99{uuid.uuid4().int % 10**12:012d}"
    identidade_teste = {
        "ticker": "TESTE11",
        "nome_emissor": f"Emissor Teste {cnpj_teste[-6:]}",
        "cnpj_emissor": cnpj_teste,
        "cod_cvm": None,
        "categoria_cvm": None,
        "tipo_capital": "Fechado",
        "status": "SUCESSO",
    }
    salvar_emissor(identidade_teste)
    emissor = buscar_emissor(cnpj_teste)
    assert emissor is not None and emissor["cnpj"] == cnpj_teste
    print(f"[ok] emissor salvo e recuperado para CNPJ {cnpj_teste}")

    hashes_qual = buscar_hashes_qualitativo(cnpj_teste)
    assert hashes_qual == set()
    print("[ok] hash qualitativo vazio para emissor novo")

    exemplo = {
        "periodos": {
            "2024-12-31": {
                "tipo": "DFP",
                "demonstracoes": {
                    "BPA": {
                        "1": {
                            "cd_conta": "1",
                            "ds_conta": "Ativo Total",
                            "valor": 123.45,
                        }
                    },
                    "DRE": {
                        "3.01": {
                            "cd_conta": "3.01",
                            "ds_conta": "Receita Liquida",
                            "valor": 67.89,
                        }
                    },
                },
            }
        }
    }
    linhas = periodos_para_linhas(cnpj_teste, exemplo)
    assert len(linhas) == 2

    total_antes = len(
        _get_client()
        .table("demonstracoes_financeiras")
        .select("id")
        .eq("cnpj", cnpj_teste)
        .execute()
        .data
        or []
    )
    salvar_demonstracoes(linhas)
    total_primeira = len(
        _get_client()
        .table("demonstracoes_financeiras")
        .select("id")
        .eq("cnpj", cnpj_teste)
        .execute()
        .data
        or []
    )
    salvar_demonstracoes(linhas)
    total_segunda = len(
        _get_client()
        .table("demonstracoes_financeiras")
        .select("id")
        .eq("cnpj", cnpj_teste)
        .execute()
        .data
        or []
    )
    periodos = buscar_periodos_demonstracoes(cnpj_teste)

    assert total_primeira == total_antes + 2
    assert total_segunda == total_primeira
    assert periodos == {"2024-12-31"}
    print("[ok] demonstracoes salvas com idempotencia confirmada")

    reconstruido = montar_demonstracoes_estruturadas(cnpj_teste)
    assert "2024-12-31" in reconstruido["periodos"]
    print("[ok] remontagem estruturada funcionando")

    print("=" * 72)
    print("Smoke test concluido com sucesso.")
    print("=" * 72)


if __name__ == "__main__":
    _smoke_test()
