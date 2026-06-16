import asyncio

from fastapi import APIRouter, HTTPException

from scripts_v2 import servico_repositorio as repo

router = APIRouter(tags=["leitura"])


@router.get("/jobs")
async def listar_jobs() -> list[dict]:
    return await asyncio.to_thread(repo.listar_jobs_recentes)


@router.get("/jobs/{job_id}")
async def obter_job(job_id: str) -> dict:
    job = await asyncio.to_thread(repo.buscar_job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job nao encontrado.")
    return job


@router.get("/portfolio")
async def obter_portfolio() -> list[dict]:
    return await asyncio.to_thread(repo.listar_portfolio)


@router.get("/proximos-pagamentos")
async def obter_proximos_pagamentos() -> list[dict]:
    return await asyncio.to_thread(repo.listar_proximos_pagamentos)


@router.get("/emissores/{cnpj}")
async def obter_emissor(cnpj: str) -> dict[str, object]:
    emissor = await asyncio.to_thread(repo.buscar_emissor, cnpj)
    if emissor is None:
        raise HTTPException(status_code=404, detail="Emissor nao encontrado.")
    debentures = await asyncio.to_thread(repo.listar_debentures_emissor, cnpj)
    return {"emissor": emissor, "debentures": debentures}
