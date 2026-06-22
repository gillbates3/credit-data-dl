import asyncio
import sys

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import rotas_cadastro, rotas_leitura
from api.config import settings
from api.seguranca import exigir_api_key

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI(title="credit-data-dl API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["infra"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(rotas_cadastro.router, dependencies=[Depends(exigir_api_key)])
app.include_router(rotas_leitura.router, dependencies=[Depends(exigir_api_key)])
