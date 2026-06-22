import asyncio

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status

from api.esquemas import CadastroTickerRequest, ProcessoCriadoResponse
from scripts_v2 import orquestrador, servico_repositorio as repo

router = APIRouter(prefix="/cadastro", tags=["cadastro"])


def _executar_cadastro_ticker_background(
    ticker: str,
    *,
    deep: bool,
    data_corte_deep: str | None,
    process_id: str,
) -> None:
    asyncio.run(
        orquestrador.ingerir_ticker(
            ticker,
            deep=deep,
            data_corte_deep=data_corte_deep,
            process_id=process_id,
        )
    )


def _executar_cadastro_documentos_background(
    cnpj: str,
    arquivos: list[tuple[str, bytes]],
    *,
    process_id: str,
) -> None:
    asyncio.run(
        orquestrador.ingerir_documentos(
            cnpj,
            arquivos,
            force=False,
            process_id=process_id,
        )
    )


@router.post(
    "/ticker",
    response_model=ProcessoCriadoResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cadastrar_ticker(
    req: CadastroTickerRequest,
    background: BackgroundTasks,
) -> ProcessoCriadoResponse:
    ticker = req.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker invalido.")

    process_id = await asyncio.to_thread(repo.criar_processo, "cadastro", ticker)
    background.add_task(
        _executar_cadastro_ticker_background,
        ticker,
        deep=req.deep,
        data_corte_deep=req.data_corte_deep,
        process_id=process_id,
    )
    return ProcessoCriadoResponse(process_id=process_id)


@router.post(
    "/documentos",
    response_model=ProcessoCriadoResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cadastrar_documentos(
    background: BackgroundTasks,
    cnpj: str = Form(...),
    arquivos: list[UploadFile] = File(...),
) -> ProcessoCriadoResponse:
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

    process_id = await asyncio.to_thread(repo.criar_processo, "cadastro", cnpj_norm)
    background.add_task(
        _executar_cadastro_documentos_background,
        cnpj_norm,
        em_memoria,
        process_id=process_id,
    )
    return ProcessoCriadoResponse(process_id=process_id)
