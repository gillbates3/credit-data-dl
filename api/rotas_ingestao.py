import asyncio

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status

from api.esquemas import IngestTickerRequest, JobCriadoResponse
from scripts_v2 import orquestrador, servico_repositorio as repo

router = APIRouter(prefix="/ingest", tags=["ingestao"])


def _executar_ingestao_ticker_background(
    ticker: str,
    *,
    deep: bool,
    data_corte_deep: str | None,
    job_id: str,
) -> None:
    asyncio.run(
        orquestrador.ingerir_ticker(
            ticker,
            deep=deep,
            data_corte_deep=data_corte_deep,
            job_id=job_id,
        )
    )


def _executar_ingestao_documentos_background(
    cnpj: str,
    arquivos: list[tuple[str, bytes]],
    *,
    job_id: str,
) -> None:
    asyncio.run(
        orquestrador.ingerir_documentos(
            cnpj,
            arquivos,
            force=False,
            job_id=job_id,
        )
    )


@router.post(
    "/ticker",
    response_model=JobCriadoResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_ticker(
    req: IngestTickerRequest,
    background: BackgroundTasks,
) -> JobCriadoResponse:
    ticker = req.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker invalido.")

    job_id = await asyncio.to_thread(repo.criar_job, "ingestao", ticker)
    background.add_task(
        _executar_ingestao_ticker_background,
        ticker,
        deep=req.deep,
        data_corte_deep=req.data_corte_deep,
        job_id=job_id,
    )
    return JobCriadoResponse(job_id=job_id)


@router.post(
    "/documentos",
    response_model=JobCriadoResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_documentos(
    background: BackgroundTasks,
    cnpj: str = Form(...),
    arquivos: list[UploadFile] = File(...),
) -> JobCriadoResponse:
    if not arquivos:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")

    em_memoria: list[tuple[str, bytes]] = []
    for arquivo in arquivos:
        try:
            conteudo = await arquivo.read()
        finally:
            await arquivo.close()
        if conteudo:
            em_memoria.append((arquivo.filename or "sem_nome.pdf", conteudo))
    if not em_memoria:
        raise HTTPException(status_code=400, detail="Arquivos vazios.")

    cnpj_norm = repo.normaliza_cnpj(cnpj)
    if not cnpj_norm:
        raise HTTPException(status_code=400, detail="CNPJ invalido.")

    job_id = await asyncio.to_thread(repo.criar_job, "ingestao", cnpj_norm)
    background.add_task(
        _executar_ingestao_documentos_background,
        cnpj_norm,
        em_memoria,
        job_id=job_id,
    )
    return JobCriadoResponse(job_id=job_id)
