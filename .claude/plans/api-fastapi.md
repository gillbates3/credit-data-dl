# Plano: API FastAPI (V2) — camada fina sobre o orquestrador

> Prompt autocontido para um agente executor (Codex). **Assuma que você não tem o histórico da conversa que gerou este plano.** Idioma do projeto: **português (pt-BR)**. Plataforma: Windows (PowerShell + Bash disponíveis). Não altere a lógica de negócio dos serviços nem do orquestrador; a API é **fina**.

---

## 1. Contexto

`credit-data-dl` é um pipeline de extração/consolidação de dados de **debêntures brasileiras** para análise de crédito. A arquitetura V2 (pasta `scripts_v2/`) tem estas camadas, **todas já prontas**:

```
Front (Next.js, futuro)  →  API (FastAPI, ESTE PLANO)  →  orquestrador.py  →  serviços + servico_repositorio.py  →  Supabase
```

- **`scripts_v2/orquestrador.py`** (assíncrono, pronto): maestro do pipeline. **Não cria jobs** — só os atualiza. Quem cria o job e passa `job_id` é a API. Dois pontos de entrada:
  - `async ingerir_ticker(ticker, *, deep=False, data_corte_deep=None, job_id=None) -> dict`
  - `async ingerir_documentos(cnpj, arquivos, *, force=False, job_id=None) -> dict` onde `arquivos: list[tuple[str, bytes]]` = `(nome_arquivo, conteudo_pdf_em_bytes)`.
  - Robustez de jobs já garantida: exceções inesperadas marcam o job como `erro` e re-lançam (o re-raise só vira log; o job **não** fica preso em `rodando`). Falhas não-fatais acumulam em `progresso["erros"]` e o status final vira `concluido_com_erros`.
- **`scripts_v2/servico_repositorio.py`** (síncrono, pronto): **única camada que conhece o Supabase**. Esta é uma **fronteira de portabilidade travada**: a API **NÃO PODE** falar com o Supabase diretamente nem importar o `supabase` client. Toda leitura/escrita passa pelo repositório. Funções relevantes já existentes:
  - `criar_job(tipo, alvo) -> job_id` (gera UUID na app), `buscar_job(job_id) -> dict|None`.
  - `buscar_emissor(cnpj) -> dict|None`.
  - `normaliza_cnpj(cnpj) -> str` (só dígitos).
  - Conexão: `_get_client()` lazy singleton; carrega `.env.local` depois `.env` da raiz; exige `SUPABASE_URL` + `SUPABASE_KEY` (service_role).
- **Serviços de IA** (`servico_ia_quantitativa.py`, `servico_ia_qualitativa.py`): carregam `GEMINI_API_KEY` de `.env.local` por conta própria. A API não precisa lidar com isso.

**Schema Supabase** (`scripts_v2/sql/supabase_schema_v2.sql`, já rodado): tabela `pipeline_jobs` (`id text` UUID, `tipo` ∈ `ingestao|analise`, `alvo`, `status` text livre: `pendente|rodando|concluido|concluido_com_erros|erro`, `etapa_atual`, `progresso` jsonb, `erro`). Views de leitura: `v_portfolio_ativo`, `v_proximos_pagamentos`, `v_emissor_debentures` (tem coluna `cnpj`, filtrável), `v_jobs_recentes` (já limitada a 100).

---

## 2. Decisões travadas (já discutidas com o dono do projeto — não reabrir)

| Decisão | Escolha |
|---|---|
| **Autenticação** | **API key única** num header `X-API-Key`, validada por dependency do FastAPI. Mono-operador. |
| **Deploy** | **Decidir depois.** Planejar agnóstico de host; rodar local com `uvicorn`. BackgroundTasks é **in-process** — se o processo reiniciar no meio, o job fica `rodando` (limitação conhecida e aceitável para ferramenta local/mono-operador; documentar, não resolver agora). |
| **Estrutura de código** | Pasta nova **`api/` na raiz** do repo. |
| **`tipo` do job para documentos** | **Reusar `ingestao`** (com `alvo=cnpj`). Ticker usa `alvo=ticker`. Sem mudança de schema. |

---

## 3. Estrutura de arquivos a criar

```
api/
  __init__.py          # vazio
  config.py            # carrega .env, expõe Settings (API_KEY, CORS origins)
  seguranca.py         # dependency de validação do X-API-Key
  esquemas.py          # modelos Pydantic de request/response
  rotas_ingestao.py    # POST /ingest/ticker, POST /ingest/documentos
  rotas_leitura.py     # GET /jobs, /jobs/{id}, /portfolio, /proximos-pagamentos, /emissores/{cnpj}
  main.py              # cria o app, monta CORS, inclui routers, /health
scripts_v2/__init__.py # criar VAZIO se ainda não existir (torna scripts_v2 importável como pacote a partir da raiz)
```

**Imports:** rode a API a partir da **raiz do repo** (`uvicorn api.main:app`), assim tanto `api` quanto `scripts_v2` ficam no `sys.path`. Dentro de `api/`, importe `from scripts_v2 import orquestrador, servico_repositorio as repo`. Criar `scripts_v2/__init__.py` vazio garante o import como pacote (o `orquestrador.py` já tem fallback `try/except ImportError` que continua funcionando ao rodar scripts diretamente).

---

## 4. Dependências (adicionar a `requirements.txt`)

Acrescentar (manter as existentes — `supabase`, `python-dotenv`, etc. já estão lá):

```
fastapi
uvicorn[standard]
python-multipart
```

`python-multipart` é obrigatório para `UploadFile`/form-data no endpoint de documentos.

---

## 5. Adições ao `scripts_v2/servico_repositorio.py` (helpers de leitura das views)

A API não pode consultar o Supabase direto, então o repositório precisa expor as views. Adicionar estas funções **síncronas** no bloco de leitura, seguindo o estilo existente (usam `_get_client()`; supabase-py consulta views via `.table(nome_view)`):

```python
def listar_jobs_recentes() -> list[dict[str, Any]]:
    """Últimos 100 jobs (view v_jobs_recentes, já ordenada/limitada)."""
    return _get_client().table("v_jobs_recentes").select("*").execute().data or []


def listar_portfolio() -> list[dict[str, Any]]:
    """Portfólio de operações ativas (view v_portfolio_ativo)."""
    return _get_client().table("v_portfolio_ativo").select("*").execute().data or []


def listar_proximos_pagamentos() -> list[dict[str, Any]]:
    """Próximos eventos de pagamento (view v_proximos_pagamentos)."""
    return _get_client().table("v_proximos_pagamentos").select("*").execute().data or []


def listar_debentures_emissor(cnpj: str) -> list[dict[str, Any]]:
    """Debêntures de um emissor (view v_emissor_debentures, filtrada por cnpj)."""
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
```

Não alterar nenhuma função existente do repositório.

---

## 6. `api/config.py`

Carrega `.env.local` e depois `.env` da raiz do repo (mesma convenção do repositório) e expõe um objeto de settings simples.

```python
import os
from pathlib import Path
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env.local")
load_dotenv(RAIZ / ".env")


class Settings:
    API_KEY: str = (os.getenv("API_KEY") or "").strip()
    # CSV de origins para o CORS; default cobre o Next.js em dev.
    CORS_ORIGINS: list[str] = [
        o.strip()
        for o in (os.getenv("CORS_ORIGINS") or "http://localhost:3000").split(",")
        if o.strip()
    ]


settings = Settings()
```

Adicionar `API_KEY=` (e opcionalmente `CORS_ORIGINS=`) ao `.env.local`. **`.env*` está no `.gitignore`** — não comitar segredos. Documentar a variável nova num comentário ou num `.env.example` se já existir.

---

## 7. `api/seguranca.py` (dependency de API key)

Header `X-API-Key`, comparação por `hmac.compare_digest` (constante no tempo). Se `API_KEY` não estiver configurada no ambiente, **recusar tudo com 500** (evita subir a API acidentalmente sem proteção).

```python
import hmac
from fastapi import Header, HTTPException, status
from api.config import settings


async def exigir_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API_KEY nao configurada no servidor.",
        )
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key invalida ou ausente.",
        )
```

A dependency é aplicada aos routers de ingestão e leitura (ver §10). O `/health` fica **fora** da autenticação.

---

## 8. `api/esquemas.py` (Pydantic)

```python
from pydantic import BaseModel, Field


class IngestTickerRequest(BaseModel):
    ticker: str = Field(..., min_length=1)
    deep: bool = False
    data_corte_deep: str | None = None  # YYYY-MM-DD


class JobCriadoResponse(BaseModel):
    job_id: str
```

(Documentos usa form-data multipart, não um body JSON — não precisa de modelo de request.)

---

## 9. `api/rotas_ingestao.py` (endpoints de escrita)

Padrão dos dois endpoints: **(1)** criar o job no repositório (via `to_thread`), **(2)** agendar a função do orquestrador em `BackgroundTasks` passando o `job_id`, **(3)** retornar `{job_id}` imediatamente. `BackgroundTasks` do FastAPI executa funções `async` no event loop — perfeito para o orquestrador.

```python
import asyncio
from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile, HTTPException, status

from scripts_v2 import orquestrador, servico_repositorio as repo
from api.esquemas import IngestTickerRequest, JobCriadoResponse

router = APIRouter(prefix="/ingest", tags=["ingestao"])


@router.post("/ticker", response_model=JobCriadoResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_ticker(req: IngestTickerRequest, background: BackgroundTasks):
    ticker = req.ticker.strip().upper()
    job_id = await asyncio.to_thread(repo.criar_job, "ingestao", ticker)
    background.add_task(
        orquestrador.ingerir_ticker,
        ticker,
        deep=req.deep,
        data_corte_deep=req.data_corte_deep,
        job_id=job_id,
    )
    return JobCriadoResponse(job_id=job_id)


@router.post("/documentos", response_model=JobCriadoResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_documentos(
    background: BackgroundTasks,
    cnpj: str = Form(...),
    arquivos: list[UploadFile] = File(...),
):
    if not arquivos:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")
    # Ler tudo para bytes EM MEMÓRIA — PDFs nunca tocam o disco.
    em_memoria: list[tuple[str, bytes]] = []
    for f in arquivos:
        conteudo = await f.read()
        if conteudo:
            em_memoria.append((f.filename or "sem_nome.pdf", conteudo))
    if not em_memoria:
        raise HTTPException(status_code=400, detail="Arquivos vazios.")

    cnpj_norm = repo.normaliza_cnpj(cnpj)
    job_id = await asyncio.to_thread(repo.criar_job, "ingestao", cnpj_norm)
    background.add_task(
        orquestrador.ingerir_documentos,
        cnpj_norm,
        em_memoria,
        force=False,
        job_id=job_id,
    )
    return JobCriadoResponse(job_id=job_id)
```

Notas:
- **PDFs em memória** (`await f.read()`), nunca gravar em disco — premissa de arquitetura.
- A validação "emissor existe?" já é feita dentro de `ingerir_documentos` (marca o job `erro` se não existir). A API não precisa replicar.
- `status_code=202 Accepted` reflete bem "aceito, processando em background".

---

## 10. `api/rotas_leitura.py` (endpoints de polling + dados)

Todas as funções do repositório são **síncronas** → chamar via `asyncio.to_thread`.

```python
import asyncio
from fastapi import APIRouter, HTTPException

from scripts_v2 import servico_repositorio as repo

router = APIRouter(tags=["leitura"])


@router.get("/jobs")
async def listar_jobs():
    return await asyncio.to_thread(repo.listar_jobs_recentes)


@router.get("/jobs/{job_id}")
async def obter_job(job_id: str):
    job = await asyncio.to_thread(repo.buscar_job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job nao encontrado.")
    return job


@router.get("/portfolio")
async def obter_portfolio():
    return await asyncio.to_thread(repo.listar_portfolio)


@router.get("/proximos-pagamentos")
async def obter_proximos_pagamentos():
    return await asyncio.to_thread(repo.listar_proximos_pagamentos)


@router.get("/emissores/{cnpj}")
async def obter_emissor(cnpj: str):
    emissor = await asyncio.to_thread(repo.buscar_emissor, cnpj)
    if emissor is None:
        raise HTTPException(status_code=404, detail="Emissor nao encontrado.")
    debentures = await asyncio.to_thread(repo.listar_debentures_emissor, cnpj)
    return {"emissor": emissor, "debentures": debentures}
```

---

## 11. `api/main.py` (app + CORS + montagem)

```python
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.seguranca import exigir_api_key
from api import rotas_ingestao, rotas_leitura

app = FastAPI(title="credit-data-dl API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],  # inclui X-API-Key e Content-Type
)


@app.get("/health", tags=["infra"])
async def health():
    return {"status": "ok"}


# Autenticação aplicada a todos os endpoints destes routers (exceto /health).
app.include_router(rotas_ingestao.router, dependencies=[Depends(exigir_api_key)])
app.include_router(rotas_leitura.router, dependencies=[Depends(exigir_api_key)])
```

---

## 12. Como rodar / verificar

**Subir a API (a partir da raiz do repo):**
```bash
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
```
Precisa de `.env.local`/`.env` com `SUPABASE_URL`, `SUPABASE_KEY` (service_role), `GEMINI_API_KEY` e a nova `API_KEY`.

**Checklist de verificação:**
1. `GET /health` → `{"status":"ok"}` **sem** header de auth.
2. `GET /jobs` **sem** `X-API-Key` → `401`. Com o header correto → lista (pode ser vazia).
3. `POST /ingest/ticker` com `{"ticker":"PETR26"}` e `X-API-Key` → `202` + `{job_id}`. Em seguida `GET /jobs/{job_id}` mostra status progredindo `rodando` → `concluido`/`concluido_com_erros`.
4. Ticker inválido → o job termina como `erro` (não fica preso em `rodando`).
5. `POST /ingest/documentos` (multipart: campo `cnpj` + um ou mais arquivos PDF) com um CNPJ **inexistente** → `202` + `{job_id}`; o job termina `erro` com mensagem "emissor inexistente; rode ingerir_ticker primeiro". Com CNPJ existente → processa quant/qual.
6. `GET /portfolio`, `GET /proximos-pagamentos`, `GET /emissores/{cnpj}` retornam dados das views (com auth).
7. Docs interativos em `http://localhost:8000/docs`.

---

## 13. Fora de escopo (não fazer agora)

- **Não** implementar `servico_analise_credito.py` nem endpoint de análise (Passo 6, deixado para o fim de propósito).
- **Não** adicionar Celery/Redis/fila externa — BackgroundTasks in-process é a decisão atual.
- **Não** adicionar multi-tenant, RLS, Supabase Auth, nem coluna de tenant.
- **Não** fazer a API falar com o Supabase diretamente — sempre via `servico_repositorio`.
- **Não** persistir PDFs em disco.
- **Não** alterar lógica/contratos do orquestrador ou dos serviços de coleta.

---

## 14. Limitação conhecida a documentar (no código ou README)

`BackgroundTasks` roda **no mesmo processo** do servidor. Se o processo for reiniciado/morto enquanto um job está `rodando`, esse job **fica preso em `rodando`** (não há worker externo para retomar). Aceitável para a fase atual (ferramenta local mono-operador). Quando o deploy for definido, reavaliar (ex.: worker dedicado ou job de "varredura de jobs órfãos").
