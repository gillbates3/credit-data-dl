import asyncio

from fastapi import APIRouter, HTTPException

from scripts_v2 import servico_repositorio as repo

router = APIRouter(tags=["leitura"])


@router.get("/processos")
async def listar_processos() -> list[dict]:
    return await asyncio.to_thread(repo.listar_processos_recentes)


@router.get("/processos/{process_id}")
async def obter_processo(process_id: str) -> dict:
    processo = await asyncio.to_thread(repo.buscar_processo, process_id)
    if processo is None:
        raise HTTPException(status_code=404, detail="Processo nao encontrado.")
    return processo


@router.get("/portfolio")
async def obter_portfolio() -> list[dict]:
    return await asyncio.to_thread(repo.listar_portfolio)


@router.get("/agenda-eventos")
async def obter_agenda_eventos() -> list[dict]:
    return await asyncio.to_thread(repo.listar_agenda_eventos)


@router.get("/ativos")
async def obter_ativos(
    identificador: str | None = None,
    resumo: bool = False,
) -> list[dict]:
    incluir_series = not resumo
    if identificador:
        resolucao = await asyncio.to_thread(
            repo.resolver_emissor_por_identificador,
            identificador,
        )
        if resolucao is None:
            raise HTTPException(status_code=404, detail="Ativo ou emissor nao encontrado.")

        if resolucao["tipo_identificador"] == "ticker_deb":
            ativo = await asyncio.to_thread(
                repo.montar_detalhe_ativo,
                resolucao.get("ticker_deb") or resolucao["identificador"],
                historico_limit=10,
            )
            return [ativo] if ativo is not None else []

        return await asyncio.to_thread(
            repo.listar_detalhes_ativos,
            resolucao["cnpj"],
            incluir_series=incluir_series,
            historico_limit=10 if incluir_series else None,
        )

    return await asyncio.to_thread(
        repo.listar_detalhes_ativos,
        incluir_series=incluir_series,
        historico_limit=10 if incluir_series else None,
    )


@router.get("/ativos/opcoes")
async def obter_opcoes_ativos(
    q: str | None = None,
    limit: int = 40,
) -> list[dict]:
    return await asyncio.to_thread(
        repo.buscar_opcoes_ativo_emissor,
        q or "",
        limit=max(1, min(limit, 200)),
    )


@router.get("/ativos/{ticker_deb}/historico")
async def obter_historico_ativo(
    ticker_deb: str,
    offset: int = 0,
    limit: int = 10,
) -> dict[str, object]:
    ativo = await asyncio.to_thread(repo.buscar_ativo_por_ticker, ticker_deb)
    if ativo is None:
        raise HTTPException(status_code=404, detail="Ativo nao encontrado.")

    return await asyncio.to_thread(
        repo.listar_historico_ativo_paginado,
        ticker_deb,
        offset=max(0, offset),
        limit=max(1, min(limit, 5000)),
    )


@router.get("/emissores/resolver/{identificador}")
async def resolver_emissor(identificador: str) -> dict[str, object]:
    resolucao = await asyncio.to_thread(
        repo.resolver_emissor_por_identificador,
        identificador,
    )
    if resolucao is None:
        raise HTTPException(status_code=404, detail="Emissor nao encontrado.")
    return resolucao


@router.get("/emissores/{cnpj}")
async def obter_emissor(cnpj: str) -> dict[str, object]:
    emissor = await asyncio.to_thread(repo.buscar_emissor, cnpj)
    if emissor is None:
        raise HTTPException(status_code=404, detail="Emissor nao encontrado.")
    debentures = await asyncio.to_thread(repo.listar_debentures_emissor, cnpj)
    return {"emissor": emissor, "debentures": debentures}


@router.get("/emissores/{cnpj}/visao-completa")
async def obter_visao_completa_emissor(cnpj: str) -> dict[str, object]:
    visao = await asyncio.to_thread(repo.montar_visao_completa_emissor, cnpj)
    if visao is None:
        raise HTTPException(status_code=404, detail="Emissor nao encontrado.")
    return visao
