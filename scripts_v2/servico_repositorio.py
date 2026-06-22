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
from concurrent.futures import ThreadPoolExecutor
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


def _chunks(seq: list[Any], n: int) -> Iterable[list[Any]]:
    for idx in range(0, len(seq), n):
        yield seq[idx : idx + n]


# Limite conservador de itens por filtro `.in_(...)` para nao estourar o tamanho
# da URL do PostgREST quando ha muitos ativos.
IN_FILTER_SIZE = 200


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


def resolver_emissor_por_identificador(identificador: str) -> dict[str, Any] | None:
    bruto = (identificador or "").strip()
    if not bruto:
        return None

    cnpj_norm = normaliza_cnpj(bruto)
    if len(cnpj_norm) == 14:
        emissor = buscar_emissor(cnpj_norm)
        if emissor is not None:
            return {
                "tipo_identificador": "cnpj",
                "identificador": cnpj_norm,
                "cnpj": cnpj_norm,
                "ticker_acao": emissor.get("ticker_acao"),
                "emissor": emissor,
            }

    ticker = bruto.upper()
    debenture = _first_or_none(
        _get_client()
        .table("deb_caracteristicas")
        .select("cnpj,ticker_deb,nome_emissor")
        .eq("ticker_deb", ticker)
        .limit(1)
        .execute()
        .data
        or []
    )
    if debenture is not None:
        emissor = buscar_emissor(debenture["cnpj"])
        if emissor is not None:
            return {
                "tipo_identificador": "ticker_deb",
                "identificador": ticker,
                "cnpj": debenture["cnpj"],
                "ticker_deb": debenture.get("ticker_deb"),
                "ticker_acao": emissor.get("ticker_acao"),
                "emissor": emissor,
            }

    emissor_acao = _first_or_none(
        _get_client()
        .table("emissores")
        .select("*")
        .eq("ticker_acao", ticker)
        .limit(1)
        .execute()
        .data
        or []
    )
    if emissor_acao is not None:
        return {
            "tipo_identificador": "ticker_acao",
            "identificador": ticker,
            "cnpj": emissor_acao["cnpj"],
            "ticker_acao": emissor_acao.get("ticker_acao"),
            "emissor": emissor_acao,
        }

    return None


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


def montar_demonstracoes_estruturadas(
    cnpj: str,
    *,
    rows: list[dict[str, Any]] | None = None,
    emissor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cnpj_norm = normaliza_cnpj(cnpj)
    periodos: dict[str, dict[str, Any]] = {}

    if not cnpj_norm:
        return {"cnpj": "", "periodos": {}}

    # `rows` e `emissor` podem ser pre-carregados pelo chamador (ex.: a visao
    # completa) para evitar reconsultar o banco. Quando ausentes, busca aqui.
    if rows is None:
        rows = _select_rows(
            "demonstracoes_financeiras",
            "data_ref,tipo_doc,demonstracao,cd_conta,ds_conta,valor",
            "cnpj",
            cnpj_norm,
        )
    if emissor is None:
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


def listar_demonstracoes_financeiras(cnpj: str) -> list[dict[str, Any]]:
    cnpj_norm = normaliza_cnpj(cnpj)
    if not cnpj_norm:
        return []

    rows = (
        _get_client()
        .table("demonstracoes_financeiras")
        .select("id,data_ref,tipo_doc,demonstracao,cd_conta,ds_conta,valor,criado_em")
        .eq("cnpj", cnpj_norm)
        .order("data_ref", desc=True)
        .order("tipo_doc", desc=True)
        .order("demonstracao")
        .order("cd_conta")
        .execute()
        .data
        or []
    )
    return rows


def listar_compendios_qualitativos(cnpj: str) -> list[dict[str, Any]]:
    cnpj_norm = normaliza_cnpj(cnpj)
    if not cnpj_norm:
        return []

    rows = (
        _get_client()
        .table("emissor_compendio_qualitativo")
        .select("id,nome_arquivo,hash_md5,titulo,markdown_conteudo,criado_em")
        .eq("cnpj", cnpj_norm)
        .order("criado_em", desc=True)
        .execute()
        .data
        or []
    )
    return rows


def listar_compendios_quantitativos(cnpj: str) -> list[dict[str, Any]]:
    cnpj_norm = normaliza_cnpj(cnpj)
    if not cnpj_norm:
        return []

    rows = (
        _get_client()
        .table("emissor_compendio_quantitativo")
        .select("id,nome_arquivo,hash_md5,titulo,criado_em")
        .eq("cnpj", cnpj_norm)
        .order("criado_em", desc=True)
        .execute()
        .data
        or []
    )
    return rows


def montar_visao_completa_emissor(cnpj: str) -> dict[str, Any] | None:
    emissor = buscar_emissor(cnpj)
    if emissor is None:
        return None

    cnpj_norm = emissor["cnpj"]

    # As leituras abaixo sao independentes entre si; o Supabase e remoto, entao
    # rodar em paralelo troca ~6 idas-e-voltas sequenciais por ~1 onda de latencia.
    with ThreadPoolExecutor(max_workers=5) as executor:
        f_debentures = executor.submit(listar_debentures_emissor, cnpj_norm)
        f_demonstracoes = executor.submit(listar_demonstracoes_financeiras, cnpj_norm)
        f_qualitativos = executor.submit(listar_compendios_qualitativos, cnpj_norm)
        f_quantitativos = executor.submit(listar_compendios_quantitativos, cnpj_norm)
        f_analise = executor.submit(buscar_ultima_analise, cnpj_norm)

        debentures = f_debentures.result()
        demonstracoes = f_demonstracoes.result()
        compendios_qualitativos = f_qualitativos.result()
        compendios_quantitativos = f_quantitativos.result()
        ultima_analise = f_analise.result()

    # Reusa as linhas ja carregadas (evita reconsultar demonstracoes_financeiras).
    estruturadas = montar_demonstracoes_estruturadas(
        cnpj_norm, rows=demonstracoes, emissor=emissor
    )

    hashes_quant = {
        item["hash_md5"]
        for item in compendios_quantitativos
        if item.get("hash_md5")
    }

    markdowns: list[dict[str, Any]] = []
    for item in compendios_qualitativos:
        markdowns.append(
            {
                "id": f"qualitativo-{item['id']}",
                "tipo": "qualitativo",
                "titulo": item.get("titulo") or item.get("nome_arquivo") or "Documento",
                "origem": item.get("nome_arquivo"),
                "hash_md5": item.get("hash_md5"),
                "financeiro": item.get("hash_md5") in hashes_quant,
                "criado_em": item.get("criado_em"),
                "conteudo": item.get("markdown_conteudo") or "",
            }
        )

    if ultima_analise is not None:
        markdowns.append(
            {
                "id": f"analise-{ultima_analise['id']}",
                "tipo": "analise_credito",
                "titulo": "Análise de crédito mais recente",
                "origem": "emissor_analise_credito",
                "financeiro": False,
                "criado_em": ultima_analise.get("criado_em"),
                "conteudo": ultima_analise.get("analise_markdown") or "",
            }
        )
        if ultima_analise.get("delta_markdown"):
            markdowns.append(
                {
                    "id": f"delta-{ultima_analise['id']}",
                    "tipo": "delta_analise",
                    "titulo": "Delta da análise mais recente",
                    "origem": "emissor_analise_credito",
                    "financeiro": False,
                    "criado_em": ultima_analise.get("criado_em"),
                    "conteudo": ultima_analise.get("delta_markdown") or "",
                }
            )

    return {
        "emissor": emissor,
        "debentures": debentures,
        "demonstracoes_financeiras": demonstracoes,
        "demonstracoes_estruturadas": estruturadas,
        "compendios_quantitativos": compendios_quantitativos,
        "markdowns": markdowns,
        "ultima_analise_credito": ultima_analise,
    }


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
    titulo: str | None = None,
) -> None:
    cnpj_norm = normaliza_cnpj(cnpj)
    if not cnpj_norm or not nome_arquivo or not hash_md5:
        raise ValueError("cnpj, nome_arquivo e hash_md5 sao obrigatorios")

    registro = {
        "cnpj": cnpj_norm,
        "nome_arquivo": nome_arquivo,
        "hash_md5": hash_md5,
        "titulo": titulo,
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


def definir_titulo_quantitativo(cnpj: str, hash_md5: str, titulo: str | None) -> None:
    cnpj_norm = normaliza_cnpj(cnpj)
    if not cnpj_norm or not hash_md5 or not titulo:
        return

    _get_client().table("emissor_compendio_quantitativo").update(
        {"titulo": titulo}
    ).eq("cnpj", cnpj_norm).eq("hash_md5", hash_md5).execute()


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


def criar_processo(tipo: str, alvo: str) -> str:
    tipo_norm = (tipo or "").strip().lower()
    if tipo_norm not in {"cadastro", "analise"}:
        raise ValueError("tipo deve ser 'cadastro' ou 'analise'")
    alvo_norm = (alvo or "").strip()
    if not alvo_norm:
        raise ValueError("alvo e obrigatorio")

    process_id = str(uuid.uuid4())
    registro = {
        "id": process_id,
        "tipo": tipo_norm,
        "alvo": alvo_norm,
        "status": "pendente",
    }
    _get_client().table("pipeline_jobs").insert(registro).execute()
    return process_id


def atualizar_processo(
    process_id: str,
    *,
    status: str | None = None,
    etapa_atual: str | None = None,
    progresso: dict[str, Any] | list[Any] | None = None,
    erro: str | None = None,
) -> None:
    if not process_id:
        raise ValueError("process_id e obrigatorio")

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

    _get_client().table("pipeline_jobs").update(payload).eq("id", process_id).execute()


def buscar_processo(process_id: str) -> dict[str, Any] | None:
    if not process_id:
        return None
    rows = _select_rows("pipeline_jobs", "*", "id", process_id)
    return _first_or_none(rows)


def listar_processos_recentes() -> list[dict[str, Any]]:
    """Ultimos 100 processos (view v_jobs_recentes, ja ordenada/limitada)."""
    return _get_client().table("v_jobs_recentes").select("*").execute().data or []


def listar_portfolio() -> list[dict[str, Any]]:
    """Portfolio de operacoes ativas (view v_portfolio_ativo)."""
    return _get_client().table("v_portfolio_ativo").select("*").execute().data or []


def listar_agenda_eventos() -> list[dict[str, Any]]:
    """Proximos eventos previstos (view v_proximos_pagamentos)."""
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


def buscar_ativo_por_ticker(ticker_deb: str) -> dict[str, Any] | None:
    ticker = (ticker_deb or "").strip().upper()
    if not ticker:
        return None
    rows = (
        _get_client()
        .table("deb_caracteristicas")
        .select(
            "id,cnpj,ticker_deb,nome_emissor,tipo,serie,numero_emissao,"
            "data_emissao,data_vencimento,data_primeiro_pagamento,prazo_anos,"
            "volume_emissao,valor_unitario_emissao,quantidade_debentures,"
            "indexador,spread_emissao,taxa_prefixada,periodicidade_juros,"
            "periodicidade_amort,especie,garantias,garantidores,lei_incentivo,"
            "banco_coordenador,banco_estruturador,agente_fiduciario,"
            "banco_liquidante,rating_emissao,agencia_rating,data_ultimo_rating,"
            "perspectiva_rating,status,isin,codigo_cetip,atualizado_em"
        )
        .eq("ticker_deb", ticker)
        .limit(1)
        .execute()
        .data
        or []
    )
    return _first_or_none(rows)


def listar_ativos(cnpj: str | None = None) -> list[dict[str, Any]]:
    query = (
        _get_client()
        .table("deb_caracteristicas")
        .select(
            "id,cnpj,ticker_deb,nome_emissor,tipo,serie,numero_emissao,"
            "data_emissao,data_vencimento,data_primeiro_pagamento,prazo_anos,"
            "volume_emissao,valor_unitario_emissao,quantidade_debentures,"
            "indexador,spread_emissao,taxa_prefixada,periodicidade_juros,"
            "periodicidade_amort,especie,garantias,garantidores,lei_incentivo,"
            "banco_coordenador,banco_estruturador,agente_fiduciario,"
            "banco_liquidante,rating_emissao,agencia_rating,data_ultimo_rating,"
            "perspectiva_rating,status,isin,codigo_cetip,atualizado_em"
        )
        .order("data_vencimento")
    )

    cnpj_norm = normaliza_cnpj(cnpj)
    if cnpj_norm:
        query = query.eq("cnpj", cnpj_norm)

    return query.execute().data or []


def listar_agenda_ativo(ticker_deb: str) -> list[dict[str, Any]]:
    ticker = (ticker_deb or "").strip().upper()
    if not ticker:
        return []
    return (
        _get_client()
        .table("deb_agenda")
        .select(
            "id,data_evento,data_liquidacao,data_base,evento,evento_arc,"
            "taxa,valor,status,grupo_status,criado_em"
        )
        .eq("ticker_deb", ticker)
        .order("data_evento")
        .execute()
        .data
        or []
    )


def contar_historico_ativo(ticker_deb: str) -> int:
    ticker = (ticker_deb or "").strip().upper()
    if not ticker:
        return 0
    rows = (
        _get_client()
        .table("deb_historico_diario")
        .select("id", count="exact")
        .eq("ticker_deb", ticker)
        .execute()
    )
    return int(rows.count or 0)


def listar_historico_ativo(
    ticker_deb: str,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    ticker = (ticker_deb or "").strip().upper()
    if not ticker:
        return []
    query = (
        _get_client()
        .table("deb_historico_diario")
        .select(
            "id,data_referencia,pu_par,vna,juros,prazo_remanescente,"
            "pu_indicativo,taxa_indicativa,taxa_compra,taxa_venda,"
            "duration_dias_uteis,desvio_padrao,percentual_pu_par,"
            "percentual_vne,intervalo_indicativo_min,intervalo_indicativo_max,"
            "referencia_ntnb,spread_indicativo,volume_financeiro,"
            "quantidade_negocios,quantidade_titulos,taxa_media_negocios,"
            "pu_medio_negocios,reune,percentual_reune,pu_indicativo_status,"
            "taxa_indicativa_status,flag_status,data_ultima_atualizacao,criado_em"
        )
        .eq("ticker_deb", ticker)
        .order("data_referencia", desc=True)
    )
    if offset > 0:
        query = query.range(offset, offset + (limit or 1000) - 1)
    elif limit is not None:
        query = query.limit(limit)

    return query.execute().data or []

def _montar_detalhe_ativo_registro(
    registro: dict[str, Any],
    *,
    historico_limit: int | None = None,
) -> dict[str, Any]:
    ticker = (registro.get("ticker_deb") or "").strip().upper()
    cnpj = registro.get("cnpj")
    historico = listar_historico_ativo(ticker, limit=historico_limit)
    historico_total = (
        contar_historico_ativo(ticker)
        if historico_limit is not None
        else len(historico)
    )
    return {
        "ticker_deb": ticker,
        "emissor": buscar_emissor(cnpj) if cnpj else None,
        "caracteristicas": registro,
        "agenda_eventos": listar_agenda_ativo(ticker),
        "historico_diario": historico,
        "historico_total": historico_total,
        "historico_tem_mais": len(historico) < historico_total,
    }


def _emissores_por_cnpjs(cnpjs: list[str]) -> dict[str, dict[str, Any]]:
    unicos = sorted({normaliza_cnpj(c) for c in cnpjs if normaliza_cnpj(c)})
    resultado: dict[str, dict[str, Any]] = {}
    for lote in _chunks(unicos, IN_FILTER_SIZE):
        rows = (
            _get_client().table("emissores").select("*").in_("cnpj", lote).execute().data
            or []
        )
        for row in rows:
            resultado[row["cnpj"]] = row
    return resultado


def _agenda_por_tickers(tickers: list[str]) -> dict[str, list[dict[str, Any]]]:
    unicos = sorted({(t or "").strip().upper() for t in tickers if t})
    grupos: dict[str, list[dict[str, Any]]] = {t: [] for t in unicos}
    for lote in _chunks(unicos, IN_FILTER_SIZE):
        rows = (
            _get_client()
            .table("deb_agenda")
            .select(
                "ticker_deb,id,data_evento,data_liquidacao,data_base,evento,"
                "evento_arc,taxa,valor,status,grupo_status,criado_em"
            )
            .in_("ticker_deb", lote)
            .order("data_evento")
            .execute()
            .data
            or []
        )
        for row in rows:
            ticker = (row.pop("ticker_deb", "") or "").strip().upper()
            grupos.setdefault(ticker, []).append(row)
    return grupos


def _historico_por_tickers(tickers: list[str]) -> dict[str, list[dict[str, Any]]]:
    unicos = sorted({(t or "").strip().upper() for t in tickers if t})
    grupos: dict[str, list[dict[str, Any]]] = {t: [] for t in unicos}
    for lote in _chunks(unicos, IN_FILTER_SIZE):
        rows = (
            _get_client()
            .table("deb_historico_diario")
            .select(
                "ticker_deb,id,data_referencia,pu_par,vna,juros,prazo_remanescente,"
                "pu_indicativo,taxa_indicativa,taxa_compra,taxa_venda,"
                "duration_dias_uteis,desvio_padrao,percentual_pu_par,"
                "percentual_vne,intervalo_indicativo_min,intervalo_indicativo_max,"
                "referencia_ntnb,spread_indicativo,volume_financeiro,"
                "quantidade_negocios,quantidade_titulos,taxa_media_negocios,"
                "pu_medio_negocios,reune,percentual_reune,pu_indicativo_status,"
                "taxa_indicativa_status,flag_status,data_ultima_atualizacao,criado_em"
            )
            .in_("ticker_deb", lote)
            .order("data_referencia", desc=True)
            .execute()
            .data
            or []
        )
        for row in rows:
            ticker = (row.pop("ticker_deb", "") or "").strip().upper()
            grupos.setdefault(ticker, []).append(row)
    return grupos


def montar_detalhe_ativo(
    ticker_deb: str,
    *,
    historico_limit: int | None = None,
) -> dict[str, Any] | None:
    registro = buscar_ativo_por_ticker(ticker_deb)
    if registro is None:
        return None
    return _montar_detalhe_ativo_registro(
        registro,
        historico_limit=historico_limit,
    )


def listar_detalhes_ativos(
    cnpj: str | None = None,
    *,
    incluir_series: bool = True,
    historico_limit: int | None = None,
) -> list[dict[str, Any]]:
    """Lista ativos ja com emissor/agenda/historico.

    Faz no maximo 4 consultas (caracteristicas + emissores + agenda + historico)
    independentemente do numero de ativos, em vez de 1 + 3N (problema de N+1).
    Com `incluir_series=False`, pula agenda e historico (uso em listagens/dropdowns
    que so precisam de ticker + emissor).
    """
    registros = listar_ativos(cnpj)
    if not registros:
        return []

    cnpjs = [r.get("cnpj") for r in registros if r.get("cnpj")]
    tickers = [r.get("ticker_deb") for r in registros if r.get("ticker_deb")]

    emissores = _emissores_por_cnpjs(cnpjs)
    agenda_por_ticker = _agenda_por_tickers(tickers) if incluir_series else {}
    historico_por_ticker = (
        _historico_por_tickers(tickers)
        if incluir_series and historico_limit is None
        else {}
    )

    detalhes: list[dict[str, Any]] = []
    for registro in registros:
        ticker = (registro.get("ticker_deb") or "").strip().upper()
        cnpj_registro = normaliza_cnpj(registro.get("cnpj"))
        if incluir_series and historico_limit is not None:
            historico_resumido = listar_historico_ativo(ticker, limit=historico_limit)
            historico_total = contar_historico_ativo(ticker)
        else:
            historico_resumido = historico_por_ticker.get(ticker, [])
            historico_total = len(historico_resumido)

        detalhes.append(
            {
                "ticker_deb": ticker,
                "emissor": emissores.get(cnpj_registro) if cnpj_registro else None,
                "caracteristicas": registro,
                "agenda_eventos": agenda_por_ticker.get(ticker, []),
                "historico_diario": historico_resumido,
                "historico_total": historico_total,
                "historico_tem_mais": len(historico_resumido) < historico_total,
            }
        )
    return detalhes


def listar_historico_ativo_paginado(
    ticker_deb: str,
    *,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    ticker = (ticker_deb or "").strip().upper()
    if not ticker:
        return {
            "ticker_deb": "",
            "items": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
            "has_more": False,
        }

    total = contar_historico_ativo(ticker)
    items = listar_historico_ativo(ticker, limit=limit, offset=offset)
    return {
        "ticker_deb": ticker,
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(items) < total,
    }


def buscar_opcoes_ativo_emissor(
    consulta: str,
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    bruto = (consulta or "").strip()
    prefixo_texto = bruto.upper()
    prefixo_cnpj = normaliza_cnpj(bruto)
    opcoes: list[dict[str, Any]] = []
    vistos: set[str] = set()

    if not bruto:
        ativos = (
            _get_client()
            .table("deb_caracteristicas")
            .select("ticker_deb,nome_emissor,cnpj")
            .order("ticker_deb")
            .limit(limit)
            .execute()
            .data
            or []
        )
    else:
        ativos_ticker = (
            _get_client()
            .table("deb_caracteristicas")
            .select("ticker_deb,nome_emissor,cnpj")
            .ilike("ticker_deb", f"{prefixo_texto}%")
            .order("ticker_deb")
            .limit(limit)
            .execute()
            .data
            or []
        )
        if prefixo_cnpj:
            ativos_cnpj = (
                _get_client()
                .table("deb_caracteristicas")
                .select("ticker_deb,nome_emissor,cnpj")
                .ilike("cnpj", f"{prefixo_cnpj}%")
                .order("ticker_deb")
                .limit(limit)
                .execute()
                .data
                or []
            )
            ativos = [*ativos_ticker, *ativos_cnpj]
        else:
            ativos_nome = (
                _get_client()
                .table("deb_caracteristicas")
                .select("ticker_deb,nome_emissor,cnpj")
                .ilike("nome_emissor", f"{prefixo_texto}%")
                .order("nome_emissor")
                .limit(limit)
                .execute()
                .data
                or []
            )
            ativos = [*ativos_ticker, *ativos_nome]

    for ativo in ativos:
        ticker = (ativo.get("ticker_deb") or "").strip().upper()
        if not ticker or ticker in vistos:
            continue
        vistos.add(ticker)
        opcoes.append(
            {
                "id": f"ativo-{ticker}",
                "value": ticker,
                "primary": ticker,
                "secondary": " · ".join(
                    [
                        parte
                        for parte in [
                            ativo.get("nome_emissor") or "Emissor sem nome",
                            normaliza_cnpj(ativo.get("cnpj")),
                        ]
                        if parte
                    ]
                ),
                "tipo": "ativo",
            }
        )

    if not bruto:
        return opcoes[:limit]

    if prefixo_cnpj:
        emissores = (
            _get_client()
            .table("emissores")
            .select("cnpj,nome,ticker_acao")
            .ilike("cnpj", f"{prefixo_cnpj}%")
            .order("cnpj")
            .limit(limit)
            .execute()
            .data
            or []
        )
    else:
        emissores_nome = (
            _get_client()
            .table("emissores")
            .select("cnpj,nome,ticker_acao")
            .ilike("nome", f"{prefixo_texto}%")
            .order("nome")
            .limit(limit)
            .execute()
            .data
            or []
        )
        emissores_ticker = (
            _get_client()
            .table("emissores")
            .select("cnpj,nome,ticker_acao")
            .ilike("ticker_acao", f"{prefixo_texto}%")
            .order("ticker_acao")
            .limit(limit)
            .execute()
            .data
            or []
        )
        emissores = [*emissores_ticker, *emissores_nome]

    for emissor in emissores:
        cnpj = normaliza_cnpj(emissor.get("cnpj"))
        if not cnpj or cnpj in vistos:
            continue
        vistos.add(cnpj)
        nome_emissor = (emissor.get("nome") or "").strip() or "Emissor sem nome"
        secundario_partes = [cnpj]
        ticker_acao = (emissor.get("ticker_acao") or "").strip().upper()
        if ticker_acao:
            secundario_partes.append(ticker_acao)
        opcoes.append(
            {
                "id": f"emissor-{cnpj}",
                "value": ticker_acao or cnpj,
                "primary": nome_emissor,
                "secondary": " · ".join(secundario_partes),
                "tipo": "emissor",
            }
        )

    return opcoes[:limit]


def _smoke_test() -> None:
    print("=" * 72)
    print("SMOKE TEST - SERVICO_REPOSITORIO")
    print("=" * 72)

    _get_client()
    print("[ok] Conexao Supabase criada.")

    process_id = criar_processo("cadastro", "TESTE11")
    atualizar_processo(process_id, status="rodando", etapa_atual="identidade")
    processo = buscar_processo(process_id)
    assert processo is not None and processo["status"] == "rodando"
    assert processo["etapa_atual"] == "identidade"
    print(f"[ok] pipeline_jobs funcionando para process_id={process_id}")

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
