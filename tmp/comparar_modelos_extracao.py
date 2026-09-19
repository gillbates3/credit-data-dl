"""
Script: tmp/comparar_modelos_extracao.py
Descrição: Harness DESCARTÁVEL de comparação entre modelos Gemini (ex.: gemini-2.5-flash
           vs gemini-3.1-flash-lite) nas duas trilhas de extração do projeto
           (qualitativa = Markdown; quantitativa = JSON CVM).

           NÃO altera código de produção. Reaproveita os prompts/helpers dos serviços
           (scripts_v2/servico_ia_qualitativa.py e servico_ia_quantitativa.py) e faz
           chamadas Gemini INSTRUMENTADAS, capturando o que os serviços não expõem:
           finish_reason (truncamento), usage_metadata (tokens) e latência. Calcula
           custo em USD e gera um relatório lado a lado para decisão do dono.

Uso:
    # listar ids de modelos disponíveis na conta (confirmar o id do 3.1 Flash-Lite)
    python tmp/comparar_modelos_extracao.py --listar-modelos

    # estimativa de custo/contagem de chunks SEM chamar a API
    python tmp/comparar_modelos_extracao.py --limite 3 --dry-run

    # comparação real (gasta tokens nos dois modelos)
    python tmp/comparar_modelos_extracao.py --limite 3 --modo ambos
    python tmp/comparar_modelos_extracao.py --arquivos formulario_de_referencia,escritura --modo ambos
"""

import argparse
import io
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations
from pathlib import Path

import requests  # noqa: E402  (DeepSeek via API OpenAI-compatível, sem novo SDK)

# --- Permite importar o pacote scripts_v2 a partir de tmp/ -------------------
PROJETO_RAIZ = Path(__file__).resolve().parent.parent
if str(PROJETO_RAIZ) not in sys.path:
    sys.path.insert(0, str(PROJETO_RAIZ))

import pdfplumber  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402
from google.genai import types  # noqa: E402

from scripts_v2 import servico_ia_qualitativa as qual  # noqa: E402
from scripts_v2 import servico_ia_quantitativa as quant  # noqa: E402

# Reusa o mesmo client/key dos serviços (carrega .env.local no import).
CLIENT = qual.CLIENT

# DeepSeek: API OpenAI-compatível (chave em .env.local, carregada via qual no import).
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_TIMEOUT = 600

# OpenAI: Chat Completions. GPT-5.x exige max_completion_tokens e NÃO aceita temperature custom.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_TIMEOUT = 600

# --- Registro de modelos (preços oficiais jun/2026, USD / 1M tokens) ---------
# Confirme o id exato do 3.1 Flash-Lite com --listar-modelos antes de rodar pra valer.
REGISTRY = {
    "gemini-2.5-flash":      {"id": "gemini-2.5-flash",      "provider": "gemini",   "preco_in": 0.30, "preco_out": 2.50, "thinking_budget": 0},
    # Gemini 2.0 Flash: custo não confirmado nesta sessão; manter 0 evita inventar preço.
    "gemini-2.0-flash":      {"id": "gemini-2.0-flash",      "provider": "gemini",   "preco_in": 0.00, "preco_out": 0.00, "thinking_budget": 0},
    "gemini-2.0-flash-001":  {"id": "gemini-2.0-flash-001",  "provider": "gemini",   "preco_in": 0.00, "preco_out": 0.00, "thinking_budget": 0},
    "gemini-2.5-flash-lite": {"id": "gemini-2.5-flash-lite", "provider": "gemini",   "preco_in": 0.10, "preco_out": 0.40, "thinking_budget": 0},
    "gemini-3.1-flash-lite": {"id": "gemini-3.1-flash-lite", "provider": "gemini",   "preco_in": 0.25, "preco_out": 1.50, "thinking_budget": 0},
    # Gemini 3 Flash Preview: preço aproximado de referência para benchmark.
    "gemini-3-flash-preview": {"id": "gemini-3-flash-preview", "provider": "gemini", "preco_in": 0.50, "preco_out": 3.00, "thinking_budget": 0},
    # Gemini 3.5 Flash: preço aproximado de referência para benchmark.
    "gemini-3.5-flash":      {"id": "gemini-3.5-flash",      "provider": "gemini",   "preco_in": 1.50, "preco_out": 9.00, "thinking_budget": 0},
    # DeepSeek V4 Flash (não-thinking p/ transcrição). 'deepseek-chat' = alias estável de V4 Flash.
    "deepseek-chat":         {"id": "deepseek-chat",         "provider": "deepseek", "preco_in": 0.14, "preco_out": 0.28, "thinking_budget": None},
    "deepseek-v4-flash":     {"id": "deepseek-v4-flash",     "provider": "deepseek", "preco_in": 0.14, "preco_out": 0.28, "thinking_budget": None},
    # DeepSeek V4 Pro (flagship de raciocínio). Preço padrão jun/2026 (promo -75% pode aplicar).
    "deepseek-v4-pro":       {"id": "deepseek-v4-pro",       "provider": "deepseek", "preco_in": 1.74, "preco_out": 3.48, "thinking_budget": None},
    # OpenAI GPT-5.4 mini (tier intermediário; raciocínio embutido). Preço mar/2026.
    "gpt-5.4-mini":          {"id": "gpt-5.4-mini",          "provider": "openai",   "preco_in": 0.75, "preco_out": 4.50, "thinking_budget": None},
    "gpt-5.4-nano":          {"id": "gpt-5.4-nano",          "provider": "openai",   "preco_in": 0.20, "preco_out": 1.25, "thinking_budget": None},
    "gpt-5.4":               {"id": "gpt-5.4",               "provider": "openai",   "preco_in": 2.50, "preco_out": 15.00, "thinking_budget": None},
}
# Set padrão da rodada atual: 3 modelos OpenAI recomendados para o benchmark.
# Sobrescrevível em runtime via --modelos.
MODELOS = [REGISTRY["gpt-5.4-nano"], REGISTRY["gpt-5.4-mini"], REGISTRY["gpt-5.4"]]

PAGINAS_POR_CHUNK_TEXTO = 8       # restrição firme do dono (evita truncamento)
PAGINAS_POR_CHUNK_VISION = qual.VISION_PAGES_PER_CHUNK  # 15
SAIDA_DIR = Path(__file__).resolve().parent / "comparacao_modelos"

PADRAO_NUMERO = re.compile(r"\d[\d.,]*\d|\d")

# --- Overrides de runtime (setados em main via CLI) -------------------------
REFORCO = False
TAG = ""
THINKING_OVERRIDE = "padrao"  # "padrao" = usa o do MODELOS; int = sobrescreve
PARALELISMO = 0  # 0 = ILIMITADO (1 worker/tarefa). >0 = teto manual se a API reclamar de RPM.
MAX_OUT_QUANT = 0  # max_output_tokens da quant (0 = default do modelo; >0 = teto alto p/ evitar MAX_TOKENS)

REFORCO_QUAL = """

REFORÇO CRÍTICO (NÃO IGNORE):
- NÃO RESUMA a narrativa: transcreva na íntegra os parágrafos da administração, comentários de desempenho operacional/financeiro, fatores de risco e justificativas. Preserve o texto; não condense em bullets curtos.
- Transcreva TODOS os números e TODAS as colunas: tanto trimestrais (ex.: 4T25, 4T24, ∆%) quanto anuais (ex.: 2025, 2024, ∆%). Não colapse colunas nem mantenha apenas o valor anual.
- Não condense tabelas: cada linha/item deve aparecer com todos os seus valores por período.
"""

REFORCO_QUANT = (
    "\n\nIMPORTANTE: extraia TODAS as contas de TODAS as demonstrações presentes "
    "(BPA, BPP, DRE, DFC, DVA), sem omitir linhas, incluindo subcontas detalhadas e seus códigos."
)


def _budget_efetivo(tb):
    return tb if THINKING_OVERRIDE == "padrao" else THINKING_OVERRIDE


# ---------------------------------------------------------------------------
# Infra de chamada instrumentada
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _preco_modelo(model_id: str) -> dict:
    for m in MODELOS:
        if m["id"] == model_id:
            return m
    return {"preco_in": 0.0, "preco_out": 0.0, "thinking_budget": None}


def _config_qual(thinking_budget):
    kwargs = {"temperature": 0.0}
    if thinking_budget is not None:
        try:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)
        except Exception:
            pass
    return types.GenerateContentConfig(**kwargs)


def _config_quant(periodos_existentes, thinking_budget):
    kwargs = {
        "system_instruction": quant.system_instruction_quantitativa(periodos_existentes or []),
        "temperature": 0.0,
        "response_mime_type": "application/json",
    }
    if thinking_budget is not None:
        try:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)
        except Exception:
            pass
    if MAX_OUT_QUANT:
        # teto alto de saída: evita o MAX_TOKENS quando o thinking come o orçamento (§8j)
        kwargs["max_output_tokens"] = MAX_OUT_QUANT
    return types.GenerateContentConfig(**kwargs)


def _usage(resp) -> dict:
    u = getattr(resp, "usage_metadata", None)
    if u is None:
        return {"prompt": 0, "saida": 0, "thinking": 0}
    return {
        "prompt": getattr(u, "prompt_token_count", 0) or 0,
        "saida": getattr(u, "candidates_token_count", 0) or 0,
        "thinking": getattr(u, "thoughts_token_count", 0) or 0,
    }


def _finish_reason(resp) -> str:
    try:
        fr = resp.candidates[0].finish_reason
    except Exception:
        return "DESCONHECIDO"
    return getattr(fr, "name", str(fr)) if fr is not None else "DESCONHECIDO"


def chamar_instrumentado(model_id: str, contents, config) -> dict:
    """Chama generate_content capturando texto, truncamento, tokens, latência e custo."""
    preco = _preco_modelo(model_id)
    for tentativa in range(3):
        inicio = time.perf_counter()
        try:
            resp = CLIENT.models.generate_content(model=model_id, contents=contents, config=config)
            latencia = time.perf_counter() - inicio
            uso = _usage(resp)
            finish = _finish_reason(resp)
            custo = (
                uso["prompt"] / 1e6 * preco["preco_in"]
                + (uso["saida"] + uso["thinking"]) / 1e6 * preco["preco_out"]
            )
            return {
                "ok": True,
                "texto": (resp.text or "") if hasattr(resp, "text") else "",
                "finish_reason": finish,
                "truncado": finish == "MAX_TOKENS",
                "latencia_s": latencia,
                "tokens": uso,
                "custo_usd": custo,
            }
        except Exception as e:
            err = str(e)
            if any(c in err for c in ("429", "503", "UNAVAILABLE")):
                # backoff exponencial COM JITTER (503/overload é frequente sob carga paralela)
                espera = (2 ** tentativa) * 10 + random.uniform(0, 5)
                log(f"    [{model_id}] erro transitório ({err[:80]}). Aguardando {espera:.1f}s...")
                time.sleep(espera)
                continue
            log(f"    [{model_id}] erro: {err[:200]}")
            return {
                "ok": False, "texto": "", "finish_reason": "ERRO", "truncado": False,
                "latencia_s": time.perf_counter() - inicio,
                "tokens": {"prompt": 0, "saida": 0, "thinking": 0}, "custo_usd": 0.0,
                "erro": err[:300],
            }
    return {
        "ok": False, "texto": "", "finish_reason": "ERRO_RETRY", "truncado": False,
        "latencia_s": 0.0, "tokens": {"prompt": 0, "saida": 0, "thinking": 0},
        "custo_usd": 0.0, "erro": "esgotou retries",
    }


def _falha_deepseek(inicio, msg) -> dict:
    return {
        "ok": False, "texto": "", "finish_reason": "ERRO", "truncado": False,
        "latencia_s": round(time.perf_counter() - inicio, 2),
        "tokens": {"prompt": 0, "saida": 0, "thinking": 0}, "custo_usd": 0.0, "erro": str(msg)[:300],
    }


def _chamar_deepseek(model_id, system_text, user_text, json_mode, max_tokens, preco) -> dict:
    """Chama a API OpenAI-compatível do DeepSeek; retorna o MESMO shape do chamar_instrumentado.

    DeepSeek V4 Flash não-thinking → tokens['thinking']=0. truncado quando finish_reason=='length'.
    """
    if not DEEPSEEK_API_KEY:
        return _falha_deepseek(time.perf_counter(), "DEEPSEEK_API_KEY ausente no .env.local")

    messages = []
    if system_text:
        messages.append({"role": "system", "content": system_text})
    messages.append({"role": "user", "content": user_text})
    payload = {"model": model_id, "messages": messages, "temperature": 0.0,
               "max_tokens": max_tokens, "stream": False}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}

    for tentativa in range(3):
        inicio = time.perf_counter()
        try:
            resp = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=DEEPSEEK_TIMEOUT)
            latencia = time.perf_counter() - inicio
            if resp.status_code == 429 or resp.status_code >= 500:
                espera = (2 ** tentativa) * 10 + random.uniform(0, 5)
                log(f"    [{model_id}] HTTP {resp.status_code} transitório. Aguardando {espera:.1f}s...")
                time.sleep(espera)
                continue
            if resp.status_code != 200:
                return _falha_deepseek(inicio, f"HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            texto = ((choice.get("message") or {}).get("content")) or ""
            finish = choice.get("finish_reason") or "DESCONHECIDO"
            usage = data.get("usage") or {}
            uso = {
                "prompt": usage.get("prompt_tokens", 0) or 0,
                "saida": usage.get("completion_tokens", 0) or 0,
                "thinking": 0,
            }
            custo = uso["prompt"] / 1e6 * preco["preco_in"] + uso["saida"] / 1e6 * preco["preco_out"]
            return {
                "ok": True, "texto": texto, "finish_reason": finish,
                "truncado": finish == "length", "latencia_s": latencia, "tokens": uso, "custo_usd": custo,
            }
        except Exception as e:
            if tentativa < 2:
                espera = (2 ** tentativa) * 5 + random.uniform(0, 3)
                log(f"    [{model_id}] erro de rede ({str(e)[:80]}). Aguardando {espera:.1f}s...")
                time.sleep(espera)
                continue
            return _falha_deepseek(inicio, e)
    return _falha_deepseek(time.perf_counter(), "esgotou retries")


def _chamar_openai(model_id, system_text, user_text, json_mode, max_tokens, preco) -> dict:
    """OpenAI Chat Completions. GPT-5.x: usa `max_completion_tokens` e NÃO envia `temperature`
    (modelos de raciocínio só aceitam o default). Mesmo shape de retorno do chamar_instrumentado.
    tokens['saida'] = completion_tokens (inclui tokens de raciocínio → custo capturado)."""
    if not OPENAI_API_KEY:
        return _falha_deepseek(time.perf_counter(), "OPENAI_API_KEY ausente no .env.local")

    messages = []
    if system_text:
        messages.append({"role": "system", "content": system_text})
    messages.append({"role": "user", "content": user_text})
    payload = {"model": model_id, "messages": messages, "max_completion_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

    for tentativa in range(3):
        inicio = time.perf_counter()
        try:
            resp = requests.post(OPENAI_URL, headers=headers, json=payload, timeout=OPENAI_TIMEOUT)
            latencia = time.perf_counter() - inicio
            if resp.status_code == 429 or resp.status_code >= 500:
                espera = (2 ** tentativa) * 10 + random.uniform(0, 5)
                log(f"    [{model_id}] HTTP {resp.status_code} transitório. Aguardando {espera:.1f}s...")
                time.sleep(espera)
                continue
            if resp.status_code != 200:
                return _falha_deepseek(inicio, f"HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            texto = ((choice.get("message") or {}).get("content")) or ""
            finish = choice.get("finish_reason") or "DESCONHECIDO"
            usage = data.get("usage") or {}
            uso = {
                "prompt": usage.get("prompt_tokens", 0) or 0,
                "saida": usage.get("completion_tokens", 0) or 0,
                "thinking": 0,
            }
            custo = uso["prompt"] / 1e6 * preco["preco_in"] + uso["saida"] / 1e6 * preco["preco_out"]
            return {
                "ok": True, "texto": texto, "finish_reason": finish,
                "truncado": finish == "length", "latencia_s": latencia, "tokens": uso, "custo_usd": custo,
            }
        except Exception as e:
            if tentativa < 2:
                espera = (2 ** tentativa) * 5 + random.uniform(0, 3)
                log(f"    [{model_id}] erro de rede ({str(e)[:80]}). Aguardando {espera:.1f}s...")
                time.sleep(espera)
                continue
            return _falha_deepseek(inicio, e)
    return _falha_deepseek(time.perf_counter(), "esgotou retries")


def _agrega_chunks(chunks: list[dict], wall_clock_s: float | None = None) -> dict:
    soma_lat = round(sum(c.get("latencia_s", 0) for c in chunks), 2)
    return {
        "n_chunks": len(chunks),
        "n_truncados": sum(1 for c in chunks if c.get("truncado")),
        "finish_reasons": [c.get("finish_reason") for c in chunks],
        # latencia_s = tempo de PAREDE do lote (paralelo); latencia_seq_s = soma (baseline sequencial)
        "latencia_s": round(wall_clock_s, 2) if wall_clock_s is not None else soma_lat,
        "latencia_seq_s": soma_lat,
        "tokens_prompt": sum(c["tokens"]["prompt"] for c in chunks),
        "tokens_saida": sum(c["tokens"]["saida"] for c in chunks),
        "tokens_thinking": sum(c["tokens"]["thinking"] for c in chunks),
        "custo_usd": round(sum(c.get("custo_usd", 0) for c in chunks), 6),
    }


def _rodar_chunks_paralelo(tarefas: list, max_workers: int) -> tuple[list[dict], float]:
    """Executa as `tarefas` (callables sem args → dict do chunk) em paralelo.

    Retorna (resultados NA ORDEM DE ENTRADA, tempo de parede em s). A ordem é
    preservada para a montagem do markdown final; o wall-clock mede o ganho real
    do paralelismo (vs a soma das latências por chunk = baseline sequencial).
    """
    n = len(tarefas)
    if n == 0:
        return [], 0.0
    # max_workers <= 0 (ou None) => ILIMITADO (1 worker por tarefa; confia no backoff de 429/5xx).
    workers = n if (max_workers is None or max_workers <= 0) else max(1, min(max_workers, n))
    resultados: list[dict | None] = [None] * n
    inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futuros = {ex.submit(fn): i for i, fn in enumerate(tarefas)}
        for fut in as_completed(futuros):
            resultados[futuros[fut]] = fut.result()
    wall = time.perf_counter() - inicio
    return [r for r in resultados if r is not None], wall


def _numeros(texto: str) -> list[str]:
    return PADRAO_NUMERO.findall(texto or "")


# ---------------------------------------------------------------------------
# Trilha qualitativa (espelha _gerar_markdown_llm / processar_pdf_texto_por_lotes)
# ---------------------------------------------------------------------------
def _detectar_scanned(conteudo: bytes) -> tuple[int, bool]:
    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        total = len(pdf.pages)
        com_texto = 0
        for p in pdf.pages:
            txt = (p.extract_text() or "").strip()
            if len(txt) >= qual.MIN_TEXT_CHARS_PER_PAGE:
                com_texto += 1
    is_scanned = total > 0 and com_texto < (total * 0.1)
    return total, is_scanned


def _chunks_texto(conteudo: bytes) -> list[tuple[int, int, str]]:
    """Retorna lista de (pag_inicio, pag_fim, texto_sanitizado) por fatia de 8 páginas."""
    fatias = []
    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        pages = pdf.pages
        total = len(pages)
        for i in range(0, total, PAGINAS_POR_CHUNK_TEXTO):
            chunk_pages = pages[i : i + PAGINAS_POR_CHUNK_TEXTO]
            partes = []
            for offset, page in enumerate(chunk_pages):
                txt = (page.extract_text() or "").strip()
                if len(txt) >= qual.MIN_TEXT_CHARS_PER_PAGE:
                    partes.append(f"\n\n--- PÁGINA {i + offset + 1} ---\n{txt}")
            bruto = "".join(partes).strip()
            if not bruto:
                continue
            limpo, _ = qual.sanitize_extracted_text(bruto)
            fatias.append((i + 1, i + len(chunk_pages), limpo))
    return fatias


def _preparar_plano_qual(conteudo: bytes) -> dict:
    """Extrai uma vez a estrutura do PDF para a trilha qualitativa.

    O objetivo é evitar repetir `_detectar_scanned` / `_chunks_texto` para cada
    modelo e permitir que TODOS os chunks entrem no mesmo pool global.
    """
    total, is_scanned = _detectar_scanned(conteudo)
    if total == 0:
        return {"erro": "PDF sem páginas", "modo": "vazio", "total_paginas": 0, "chunks": []}

    if not is_scanned:
        fatias = _chunks_texto(conteudo)
        return {
            "erro": None,
            "modo": "texto",
            "total_paginas": total,
            "chunks": [
                {"ordem": ordem, "pi": pi, "pf": pf, "texto": texto}
                for ordem, (pi, pf, texto) in enumerate(fatias)
            ],
        }

    reader = PdfReader(io.BytesIO(conteudo))
    chunks = []
    for ordem, i in enumerate(range(0, total, PAGINAS_POR_CHUNK_VISION)):
        pi, pf = i + 1, min(i + PAGINAS_POR_CHUNK_VISION, total)
        writer = PdfWriter()
        for idx in range(i, pf):
            writer.add_page(reader.pages[idx])
        buf = io.BytesIO()
        writer.write(buf)
        chunks.append({"ordem": ordem, "pi": pi, "pf": pf, "payload": buf.getvalue()})
    return {"erro": None, "modo": "vision", "total_paginas": total, "chunks": chunks}


def _executar_chunk_qual(model_id: str, thinking_budget, cnpj: str, nome: str, plano: dict, chunk: dict) -> dict:
    """Executa UM chunk qualitativo; usado no pool global junto dos quants."""
    provider = _preco_modelo(model_id).get("provider", "gemini")
    total = plano["total_paginas"]
    pi, pf = chunk["pi"], chunk["pf"]
    config = _config_qual(thinking_budget)
    inicio = time.perf_counter()

    if plano["modo"] == "texto":
        nome_chunk = f"{nome} (Páginas {pi} a {pf} de {total})"
        prompt = (
            f"CNPJ: {cnpj}\nArquivo: {nome_chunk}\n\n{qual.PROMPT_QUALITATIVO}"
            f"{REFORCO_QUAL if REFORCO else ''}\n\n"
            f"Texto extraído do PDF:\n{chunk['texto']}"
        )
        log(f"    [qual/{model_id}] -> chunk páginas {pi}-{pf}/{total} (disparado)")
        if provider == "deepseek":
            r = _chamar_deepseek(model_id, "", prompt, False, 32000, _preco_modelo(model_id))
        elif provider == "openai":
            r = _chamar_openai(model_id, "", prompt, False, 32000, _preco_modelo(model_id))
        else:
            r = chamar_instrumentado(model_id, prompt, config)
        log(f"    [qual/{model_id}] <- chunk páginas {pi}-{pf}/{total} ({r['latencia_s']:.1f}s)")
    else:
        if provider in ("deepseek", "openai"):
            r = {
                "ok": False,
                "texto": "",
                "finish_reason": "VISION_SKIP",
                "truncado": False,
                "latencia_s": 0.0,
                "tokens": {"prompt": 0, "saida": 0, "thinking": 0},
                "custo_usd": 0.0,
                "erro": f"{provider}_sem_vision_no_harness",
            }
        else:
            nome_chunk = f"{nome} (Páginas {pi} a {pf} de {total})"
            log(f"    [qual/{model_id}] -> VISION páginas {pi}-{pf}/{total} (disparado)")
            r = _chamar_vision(model_id, config, cnpj, nome_chunk, chunk["payload"])
            log(f"    [qual/{model_id}] <- VISION páginas {pi}-{pf}/{total} ({r['latencia_s']:.1f}s)")

    r["_ordem"] = chunk["ordem"]
    r["_started_at"] = inicio
    r["_ended_at"] = time.perf_counter()
    return r


def _agregar_resultado_qual(plano: dict, chunks_meta: list[dict]) -> dict:
    """Monta o markdown final da qual a partir dos chunks já executados."""
    ordenados = sorted(chunks_meta, key=lambda c: c.get("_ordem", 0))
    partes_md = [r["texto"] for r in ordenados if r.get("ok") and r.get("texto")]
    markdown_bruto = "\n\n".join(partes_md).strip()
    markdown, _ = qual.sanitize_generated_markdown(markdown_bruto) if markdown_bruto else ("", 0)

    if ordenados:
        wall = max(c.get("_ended_at", 0) for c in ordenados) - min(c.get("_started_at", 0) for c in ordenados)
    else:
        wall = 0.0

    agg = _agrega_chunks(ordenados, wall_clock_s=wall)
    agg.update({
        "modo": plano["modo"],
        "total_paginas": plano["total_paginas"],
        "chars_saida": len(markdown),
        "n_numeros": len(_numeros(markdown)),
        "markdown": markdown,
    })
    return agg


def _preparar_quant(nome: str, conteudo: bytes) -> dict:
    if not quant.is_financial_pdf_name(nome):
        return {"pulado": True, "motivo": "heuristica_nome_nao_financeiro"}
    texto, is_scanned = quant.extract_financial_pages_text_from_bytes(conteudo, nome)
    return {"pulado": False, "texto": texto, "is_scanned": is_scanned}


def processar_qual(model_id: str, thinking_budget, cnpj: str, nome: str, conteudo: bytes) -> dict:
    total, is_scanned = _detectar_scanned(conteudo)
    chunks_meta: list[dict] = []
    partes_md: list[str] = []

    if total == 0:
        return {"erro": "PDF sem páginas", "modo": "vazio"}

    provider = _preco_modelo(model_id).get("provider", "gemini")
    if is_scanned and provider in ("deepseek", "openai"):
        # harness só tem caminho vision pelo Gemini (Files API); para esses, pula escaneado.
        return {"erro": f"{provider}_sem_vision_no_harness", "modo": "vision_skip"}

    if not is_scanned:
        modo = "texto"
        config = _config_qual(thinking_budget)
        fatias = _chunks_texto(conteudo)
        tarefas = []
        for pi, pf, texto in fatias:
            nome_chunk = f"{nome} (Páginas {pi} a {pf} de {total})"
            prompt = (
                f"CNPJ: {cnpj}\nArquivo: {nome_chunk}\n\n{qual.PROMPT_QUALITATIVO}"
                f"{REFORCO_QUAL if REFORCO else ''}\n\n"
                f"Texto extraído do PDF:\n{texto}"
            )

            def faz(prompt=prompt, pi=pi, pf=pf):
                log(f"    [qual/{model_id}] -> chunk páginas {pi}-{pf}/{total} (disparado)")
                if provider == "deepseek":
                    # 32k de saída: headroom p/ v4-pro (raciocínio consome orçamento antes da transcrição).
                    r = _chamar_deepseek(model_id, "", prompt, False, 32000, _preco_modelo(model_id))
                elif provider == "openai":
                    r = _chamar_openai(model_id, "", prompt, False, 32000, _preco_modelo(model_id))
                else:
                    r = chamar_instrumentado(model_id, prompt, config)
                log(f"    [qual/{model_id}] <- chunk páginas {pi}-{pf}/{total} ({r['latencia_s']:.1f}s)")
                return r

            tarefas.append(faz)
        log(f"    [qual/{model_id}] {len(tarefas)} chunks em PARALELO (paralelismo={'ilimitado' if PARALELISMO <= 0 else PARALELISMO})...")
        chunks_meta, wall = _rodar_chunks_paralelo(tarefas, PARALELISMO)
    else:
        modo = "vision"
        config = _config_qual(thinking_budget)
        reader = PdfReader(io.BytesIO(conteudo))
        total = len(reader.pages)
        tarefas = []
        for i in range(0, total, PAGINAS_POR_CHUNK_VISION):
            pi, pf = i + 1, min(i + PAGINAS_POR_CHUNK_VISION, total)
            writer = PdfWriter()
            for idx in range(i, pf):
                writer.add_page(reader.pages[idx])
            buf = io.BytesIO()
            writer.write(buf)
            nome_chunk = f"{nome} (Páginas {pi} a {pf} de {total})"
            payload = buf.getvalue()

            def faz(payload=payload, nome_chunk=nome_chunk, pi=pi, pf=pf):
                log(f"    [qual/{model_id}] -> VISION páginas {pi}-{pf}/{total} (disparado)")
                r = _chamar_vision(model_id, config, cnpj, nome_chunk, payload)
                log(f"    [qual/{model_id}] <- VISION páginas {pi}-{pf}/{total} ({r['latencia_s']:.1f}s)")
                return r

            tarefas.append(faz)
        log(f"    [qual/{model_id}] {len(tarefas)} chunks VISION em PARALELO (paralelismo={'ilimitado' if PARALELISMO <= 0 else PARALELISMO})...")
        chunks_meta, wall = _rodar_chunks_paralelo(tarefas, PARALELISMO)

    for r in chunks_meta:
        if r["ok"] and r["texto"]:
            partes_md.append(r["texto"])

    markdown_bruto = "\n\n".join(partes_md).strip()
    markdown, _ = qual.sanitize_generated_markdown(markdown_bruto) if markdown_bruto else ("", 0)
    agg = _agrega_chunks(chunks_meta, wall_clock_s=wall)
    agg.update({
        "modo": modo,
        "total_paginas": total,
        "chars_saida": len(markdown),
        "n_numeros": len(_numeros(markdown)),
        "markdown": markdown,
    })
    return agg


def _chamar_vision(model_id, config, cnpj, nome, conteudo) -> dict:
    """Upload + generate_content instrumentado para PDF escaneado (uma fatia)."""
    import tempfile

    uploaded = None
    temp_path = None
    preco = _preco_modelo(model_id)
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(conteudo)
            temp_path = tmp.name
        uploaded = CLIENT.files.upload(
            file=temp_path, config=types.UploadFileConfig(mime_type="application/pdf")
        )
        while qual.file_state_name(CLIENT.files.get(name=uploaded.name)) == "PROCESSING":
            time.sleep(2)
        file_info = CLIENT.files.get(name=uploaded.name)
        if qual.file_state_name(file_info) == "FAILED":
            return {"ok": False, "texto": "", "finish_reason": "UPLOAD_FAILED", "truncado": False,
                    "latencia_s": 0.0, "tokens": {"prompt": 0, "saida": 0, "thinking": 0}, "custo_usd": 0.0}
        prompt = f"CNPJ: {cnpj}\nArquivo: {nome}\n\n{qual.PROMPT_QUALITATIVO}{REFORCO_QUAL if REFORCO else ''}"
        inicio = time.perf_counter()
        resp = CLIENT.models.generate_content(model=model_id, contents=[prompt, file_info], config=config)
        latencia = time.perf_counter() - inicio
        uso = _usage(resp)
        finish = _finish_reason(resp)
        custo = uso["prompt"] / 1e6 * preco["preco_in"] + (uso["saida"] + uso["thinking"]) / 1e6 * preco["preco_out"]
        return {"ok": True, "texto": resp.text or "", "finish_reason": finish,
                "truncado": finish == "MAX_TOKENS", "latencia_s": latencia, "tokens": uso, "custo_usd": custo}
    except Exception as e:
        return {"ok": False, "texto": "", "finish_reason": "ERRO", "truncado": False, "latencia_s": 0.0,
                "tokens": {"prompt": 0, "saida": 0, "thinking": 0}, "custo_usd": 0.0, "erro": str(e)[:300]}
    finally:
        if uploaded is not None:
            try:
                CLIENT.files.delete(name=uploaded.name)
            except Exception:
                pass
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Trilha quantitativa (espelha extrair_dados_quantitativos, 1 arquivo)
# ---------------------------------------------------------------------------
def processar_quant(model_id: str, thinking_budget, cnpj: str, nome: str, conteudo: bytes,
                    periodos_existentes=None, prepared: dict | None = None) -> dict:
    if prepared is None:
        prepared = _preparar_quant(nome, conteudo)
    if prepared.get("pulado"):
        return {"pulado": True, "motivo": prepared.get("motivo", "heuristica_nome_nao_financeiro")}

    texto = prepared.get("texto", "")
    is_scanned = prepared.get("is_scanned", False)
    config = _config_quant(periodos_existentes, thinking_budget)
    provider = _preco_modelo(model_id).get("provider", "gemini")

    if texto and not is_scanned:
        prompt = (
            f"CNPJ: {cnpj}\nArquivo: {nome}\n\n"
            f"Texto das páginas financeiras extraído do PDF:\n{texto}\n\n"
            f"Extraia os dados financeiros no formato JSON conforme instruído."
            f"{REFORCO_QUANT if REFORCO else ''}"
        )
        if provider in ("deepseek", "openai"):
            sys_txt = quant.system_instruction_quantitativa(periodos_existentes or [])
            chamar = _chamar_deepseek if provider == "deepseek" else _chamar_openai
            r = chamar(model_id, sys_txt, prompt, True, (MAX_OUT_QUANT or 32000), _preco_modelo(model_id))
        else:
            r = chamar_instrumentado(model_id, prompt, config)
    elif provider in ("deepseek", "openai"):
        r = _falha_deepseek(time.perf_counter(), f"{provider}_sem_vision_no_harness (PDF sem texto/escaneado)")
        r["finish_reason"] = "VISION_SKIP"
    else:
        r = _chamar_vision(model_id, config, cnpj, nome, conteudo)

    consolidated = quant.criar_json_base(cnpj)
    n_periodos = 0
    parsed = None
    erro = r.get("erro")
    if r["ok"] and r["texto"]:
        try:
            bruto = json.loads(r["texto"])
        except Exception as e:
            erro = f"json_parse: {str(e)[:240]}"
            parsed = None
        else:
            try:
                parsed = quant.normalizar_resposta_ia(bruto)
            except Exception as e:
                erro = f"json_normalizacao: {str(e)[:240]}"
                parsed = None
            if parsed:
                n_periodos = quant.merge_periods(consolidated, parsed)
            elif not erro:
                erro = "json_vazio_ou_incompativel"

    n_contas = sum(
        len(contas)
        for periodo in consolidated.get("periodos", {}).values()
        for contas in periodo.get("demonstracoes", {}).values()
        if isinstance(contas, dict)
    )
    return {
        "pulado": False,
        "modo": "texto" if (texto and not is_scanned) else "vision",
        "ok": r["ok"],
        "finish_reason": r["finish_reason"],
        "truncado": r["truncado"],
        "latencia_s": round(r["latencia_s"], 2),
        "tokens_prompt": r["tokens"]["prompt"],
        "tokens_saida": r["tokens"]["saida"],
        "tokens_thinking": r["tokens"]["thinking"],
        "custo_usd": round(r["custo_usd"], 6),
        "n_periodos": len(consolidated.get("periodos", {})),
        "n_periodos_novos": n_periodos,
        "n_contas": n_contas,
        "erro": erro,
        "json": consolidated,
    }


# ---------------------------------------------------------------------------
# Dry-run (sem API)
# ---------------------------------------------------------------------------
def dry_run(arquivos, cnpj, modo):
    log("=== DRY-RUN (sem chamadas à API) ===")
    total_chunks_qual = 0
    for nome, conteudo in arquivos:
        total, is_scanned = _detectar_scanned(conteudo)
        if modo in ("qual", "ambos"):
            if not is_scanned:
                fatias = _chunks_texto(conteudo)
                chars = sum(len(t) for _, _, t in fatias)
                total_chunks_qual += len(fatias)
                log(f"  {nome[:60]:60} | {total:>3} págs | qual: {len(fatias)} chunk(s) texto | ~{chars // 4:,} tok in")
            else:
                n = -(-total // PAGINAS_POR_CHUNK_VISION)
                total_chunks_qual += n
                log(f"  {nome[:60]:60} | {total:>3} págs | qual: {n} chunk(s) VISION (escaneado)")
        if modo in ("quant", "ambos"):
            if quant.is_financial_pdf_name(nome):
                texto, sc = quant.extract_financial_pages_text_from_bytes(conteudo, nome)
                log(f"  {' ':60} | quant: 1 chamada | ~{len(texto) // 4:,} tok in | {'vision' if sc or not texto else 'texto'}")
            else:
                log(f"  {' ':60} | quant: PULADO (heurística de nome)")
    n_quant = sum(1 for n, _ in arquivos if quant.is_financial_pdf_name(n)) if modo in ("quant", "ambos") else 0
    n_qual = total_chunks_qual if modo in ("qual", "ambos") else 0
    req_por_modelo = n_qual + n_quant
    log("-" * 80)
    log(f"Requisições por modelo: {req_por_modelo}  (qual={n_qual} chunks + quant={n_quant} arquivos)")
    log(f"Total estimado em {len(MODELOS)} modelo(s): {req_por_modelo * len(MODELOS)} requisições")
    log("Custo de OUTPUT não é estimável sem rodar (depende do tamanho da transcrição).")


# ---------------------------------------------------------------------------
# Execução real + relatório
# ---------------------------------------------------------------------------
def _slug(mid: str) -> str:
    """Nome de pasta por modelo, incluindo a TAG (evita ler saídas de outra run)."""
    return (mid + (f"__{TAG}" if TAG else "")).replace("/", "_")


def _job_qual(nome, conteudo, m, cnpj):
    mid = m["id"]
    tb = _budget_efetivo(m["thinking_budget"])
    log(f"  -> QUAL {mid} | {nome}")
    rq = processar_qual(mid, tb, cnpj, nome, conteudo)
    md = rq.pop("markdown", "")
    (SAIDA_DIR / "por_modelo" / _slug(mid) / f"{nome}.qual.md").write_text(md, encoding="utf-8")
    log(f"  <- QUAL {mid} | {nome} ({rq.get('latencia_s', 0)}s parede)")
    return ("qual", nome, mid, rq)


def _job_quant(nome, conteudo, m, cnpj, prepared_quant=None):
    mid = m["id"]
    tb = _budget_efetivo(m["thinking_budget"])
    log(f"  -> QUANT {mid} | {nome}")
    rqt = processar_quant(mid, tb, cnpj, nome, conteudo, prepared=prepared_quant)
    js = rqt.pop("json", None)
    if js is not None:
        (SAIDA_DIR / "por_modelo" / _slug(mid) / f"{nome}.quant.json").write_text(
            json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    log(f"  <- QUANT {mid} | {nome} ({rqt.get('latencia_s', 0)}s)")
    return ("quant", nome, mid, rqt)


def executar(arquivos, cnpj, modo):
    SAIDA_DIR.mkdir(parents=True, exist_ok=True)
    for m in MODELOS:
        (SAIDA_DIR / "por_modelo" / _slug(m["id"])).mkdir(parents=True, exist_ok=True)

    relatorio = {"cnpj": cnpj, "modo": modo, "modelos": [m["id"] for m in MODELOS]}
    itens = {nome: {"arquivo": nome, "tamanho_kb": round(len(c) / 1024, 1), "qual": {}, "quant": {}}
             for nome, c in arquivos}

    qual_planos = {}
    quant_planos = {}
    prep_jobs = []
    if modo in ("qual", "ambos"):
        for nome, conteudo in arquivos:
            prep_jobs.append(lambda nome=nome, conteudo=conteudo: ("qual_prep", nome, _preparar_plano_qual(conteudo)))
    if modo in ("quant", "ambos"):
        for nome, conteudo in arquivos:
            prep_jobs.append(lambda nome=nome, conteudo=conteudo: ("quant_prep", nome, _preparar_quant(nome, conteudo)))
    if prep_jobs:
        log(f"Preparando entradas compartilhadas ({len(prep_jobs)} tarefa(s)) antes do disparo global...")
        prep_res, _ = _rodar_chunks_paralelo(prep_jobs, PARALELISMO)
        for track, nome, payload in prep_res:
            if track == "qual_prep":
                qual_planos[nome] = payload
            else:
                quant_planos[nome] = payload

    # PARALELISMO TOTAL REAL: quant e CADA chunk da qual entram no MESMO pool global.
    # Assim o job qualitativo não "espera" o quant terminar para só então abrir os chunks.
    jobs = []
    qual_erros = {}
    for nome, conteudo in arquivos:
        for m in MODELOS:
            if modo in ("qual", "ambos"):
                plano = qual_planos[nome]
                mid = m["id"]
                provider = _preco_modelo(mid).get("provider", "gemini")
                if plano.get("erro"):
                    qual_erros[(nome, mid)] = {"erro": plano["erro"], "modo": plano.get("modo", "vazio")}
                elif plano["modo"] == "vision" and provider in ("deepseek", "openai"):
                    qual_erros[(nome, mid)] = {"erro": f"{provider}_sem_vision_no_harness", "modo": "vision_skip"}
                else:
                    for chunk in plano["chunks"]:
                        tb = _budget_efetivo(m["thinking_budget"])
                        jobs.append(
                            lambda nome=nome, mid=mid, tb=tb, plano=plano, chunk=chunk:
                                ("qual_chunk", nome, mid, _executar_chunk_qual(mid, tb, cnpj, nome, plano, chunk))
                        )
            if modo in ("quant", "ambos"):
                prepared_quant = quant_planos[nome]
                jobs.append(
                    lambda nome=nome, conteudo=conteudo, m=m, prepared_quant=prepared_quant:
                        _job_quant(nome, conteudo, m, cnpj, prepared_quant)
                )

    paral = "ilimitado" if PARALELISMO <= 0 else str(PARALELISMO)
    log(f"Disparando {len(jobs)} jobs globais (quant + chunks quali) em PARALELO TOTAL "
        f"(paralelismo={paral}).")
    resultados, wall_total = _rodar_chunks_paralelo(jobs, PARALELISMO)

    qual_chunks = {}
    for track, nome, mid, res in resultados:
        if track == "qual_chunk":
            qual_chunks.setdefault((nome, mid), []).append(res)
        else:
            itens[nome][track][mid] = res

    for (nome, mid), res in qual_erros.items():
        itens[nome]["qual"][mid] = res

    if modo in ("qual", "ambos"):
        for nome, _ in arquivos:
            for m in MODELOS:
                mid = m["id"]
                if mid in itens[nome]["qual"]:
                    continue
                chunks_meta = qual_chunks.get((nome, mid), [])
                if not chunks_meta:
                    continue
                rq = _agregar_resultado_qual(qual_planos[nome], chunks_meta)
                md = rq.pop("markdown", "")
                (SAIDA_DIR / "por_modelo" / _slug(mid) / f"{nome}.qual.md").write_text(md, encoding="utf-8")
                itens[nome]["qual"][mid] = rq

    # fidelidade numérica par-a-par (qual) — depois que TODOS os jobs terminaram
    if modo in ("qual", "ambos") and len(MODELOS) >= 2:
        pares = [(a["id"], b["id"]) for a, b in combinations(MODELOS, 2)]
        for nome in itens:
            comparativos = []
            for a, b in pares:
                pa = SAIDA_DIR / "por_modelo" / _slug(a) / f"{nome}.qual.md"
                pb = SAIDA_DIR / "por_modelo" / _slug(b) / f"{nome}.qual.md"
                if pa.exists() and pb.exists():
                    na = set(_numeros(pa.read_text(encoding="utf-8")))
                    nb = set(_numeros(pb.read_text(encoding="utf-8")))
                    comparativos.append({
                        "modelo_a": a,
                        "modelo_b": b,
                        "numeros_a": len(na),
                        "numeros_b": len(nb),
                        "so_em_a": len(na - nb),
                        "so_em_b": len(nb - na),
                        "em_comum": len(na & nb),
                    })
            if comparativos:
                itens[nome]["fidelidade_numerica_qual"] = comparativos

    relatorio["arquivos"] = [itens[nome] for nome, _ in arquivos]
    relatorio["wall_total_s"] = round(wall_total, 2)

    nome_rel = f"relatorio{('_' + TAG) if TAG else ''}"
    (SAIDA_DIR / f"{nome_rel}.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    _escrever_relatorio_md(relatorio, modo, nome_rel)
    log(f"\nWall-clock total: {wall_total:.1f}s. Relatório salvo em {SAIDA_DIR} ({nome_rel}.md)")


def _escrever_relatorio_md(relatorio, modo, nome_rel="relatorio"):
    L = ["# Comparação de modelos — extração de PDFs", "",
         f"- CNPJ: `{relatorio['cnpj']}`  |  Modo: `{modo}`  |  Modelos: {', '.join(relatorio['modelos'])}",
         "- **Critério final = leitura humana das saídas** em `por_modelo/`. As tabelas abaixo apontam onde olhar.", ""]

    if modo in ("qual", "ambos"):
        L += ["## Trilha qualitativa (markdown)", "",
              f"> Chunks de 8 págs enviados **em paralelo** (paralelismo={'ilimitado' if PARALELISMO <= 0 else PARALELISMO}). "
              "**Latência (s)** = tempo de parede do lote paralelo; **Seq (s)** = soma das latências por chunk "
              "(= baseline sequencial); **Speedup** = Seq / parede.", "",
              "| Arquivo | Modelo | Modo | Chunks | **Truncados** | Latência (s) | Seq (s) | **Speedup** | Tok in | Tok out | Tok think | Custo USD | Chars | Nº números |",
              "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for it in relatorio["arquivos"]:
            for mid, r in it.get("qual", {}).items():
                if r.get("erro"):
                    L.append(f"| {it['arquivo'][:40]} | {mid} | ERRO | - | - | - | - | - | - | - | - | - | - | - |")
                    continue
                par = r.get("latencia_s", 0) or 0
                seq = r.get("latencia_seq_s", 0) or 0
                speedup = f"{seq / par:.1f}x" if par else "-"
                L.append(
                    f"| {it['arquivo'][:40]} | {mid} | {r.get('modo','')} | {r.get('n_chunks',0)} | "
                    f"{r.get('n_truncados',0)} | {par} | {seq} | {speedup} | {r.get('tokens_prompt',0)} | "
                    f"{r.get('tokens_saida',0)} | {r.get('tokens_thinking',0)} | {r.get('custo_usd',0):.4f} | "
                    f"{r.get('chars_saida',0)} | {r.get('n_numeros',0)} |"
                )
        L.append("")
        L.append("### Fidelidade numérica (divergência par-a-par, qual)")
        L.append("| Arquivo | Modelo A | Modelo B | Nº A | Nº B | Só em A | Só em B | Em comum |")
        L.append("|---|---|---|---:|---:|---:|---:|---:|")
        for it in relatorio["arquivos"]:
            for f in it.get("fidelidade_numerica_qual", []):
                L.append(
                    f"| {it['arquivo'][:40]} | {f['modelo_a']} | {f['modelo_b']} | {f['numeros_a']} | "
                    f"{f['numeros_b']} | {f['so_em_a']} | {f['so_em_b']} | {f['em_comum']} |"
                )
        L.append("")

    if modo in ("quant", "ambos"):
        L += ["## Trilha quantitativa (JSON CVM)", "",
              "| Arquivo | Modelo | Modo | **Trunc.** | Latência (s) | Tok in | Tok out | Tok think | Custo USD | Períodos | Contas |",
              "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        for it in relatorio["arquivos"]:
            for mid, r in it.get("quant", {}).items():
                if r.get("pulado"):
                    L.append(f"| {it['arquivo'][:40]} | {mid} | PULADO ({r.get('motivo','')}) | - | - | - | - | - | - | - | - |")
                    continue
                if r.get("erro"):
                    L.append(
                        f"| {it['arquivo'][:40]} | {mid} | ERRO ({r.get('erro','')[:40]}) | "
                        f"{'SIM' if r.get('truncado') else 'não'} | {r.get('latencia_s',0)} | "
                        f"{r.get('tokens_prompt',0)} | {r.get('tokens_saida',0)} | {r.get('tokens_thinking',0)} | "
                        f"{r.get('custo_usd',0):.4f} | {r.get('n_periodos',0)} | {r.get('n_contas',0)} |"
                    )
                    continue
                L.append(
                    f"| {it['arquivo'][:40]} | {mid} | {r.get('modo','')} | {'SIM' if r.get('truncado') else 'não'} | "
                    f"{r.get('latencia_s',0)} | {r.get('tokens_prompt',0)} | {r.get('tokens_saida',0)} | "
                    f"{r.get('tokens_thinking',0)} | {r.get('custo_usd',0):.4f} | {r.get('n_periodos',0)} | {r.get('n_contas',0)} |"
                )
        L.append("")

    # agregado por modelo
    L += ["## Agregado por modelo", "", "| Modelo | Custo USD total | Latência total (s) | Chunks truncados (qual) |",
          "|---|---:|---:|---:|"]
    for mid in relatorio["modelos"]:
        custo = sum(it.get("qual", {}).get(mid, {}).get("custo_usd", 0) for it in relatorio["arquivos"])
        custo += sum(it.get("quant", {}).get(mid, {}).get("custo_usd", 0) for it in relatorio["arquivos"])
        lat = sum(it.get("qual", {}).get(mid, {}).get("latencia_s", 0) for it in relatorio["arquivos"])
        lat += sum(it.get("quant", {}).get(mid, {}).get("latencia_s", 0) for it in relatorio["arquivos"])
        trunc = sum(it.get("qual", {}).get(mid, {}).get("n_truncados", 0) for it in relatorio["arquivos"])
        L.append(f"| {mid} | {custo:.4f} | {round(lat, 1)} | {trunc} |")

    (SAIDA_DIR / f"{nome_rel}.md").write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------------------
def selecionar_arquivos(pasta: Path, filtros: list[str], limite: int):
    todos = qual.carregar_arquivos_em_memoria(pasta)
    if filtros:
        f = [s.lower() for s in filtros]
        todos = [(n, c) for (n, c) in todos if any(s in n.lower() for s in f)]
    return todos[:limite] if limite else todos


def main():
    global REFORCO, TAG, THINKING_OVERRIDE, MODELOS, PARALELISMO, MAX_OUT_QUANT
    ap = argparse.ArgumentParser(description="Compara modelos nas trilhas de extração.")
    ap.add_argument("pasta", nargs="?",
                    default=str(PROJETO_RAIZ / "data" / "01_landing" / "manual_uploads" / "02041460000193" / "Principal"),
                    help="Pasta com PDFs (default: corpus V.tal).")
    ap.add_argument("--cnpj", default="02041460000193")
    ap.add_argument("--limite", type=int, default=3, help="Máx. de arquivos (default 3; gasta tokens reais).")
    ap.add_argument("--arquivos", default="", help="Filtro por substrings no nome, separadas por vírgula.")
    ap.add_argument("--modo", choices=["qual", "quant", "ambos"], default="ambos")
    ap.add_argument("--dry-run", action="store_true", help="Estima custo/chunks sem chamar a API.")
    ap.add_argument("--listar-modelos", action="store_true", help="Lista ids de modelos disponíveis e sai.")
    ap.add_argument("--apenas-modelo", default="", help="Roda só este id de modelo (ex.: gemini-3.1-flash-lite).")
    ap.add_argument("--thinking", default=None, help="Override do thinking_budget (-1 dinâmico, 0 off, >0 cap).")
    ap.add_argument("--reforco", action="store_true", help="Acrescenta reforço anti-resumo ao prompt (qual+quant).")
    ap.add_argument("--tag", default="", help="Sufixo p/ pastas/relatório (evita sobrescrever runs anteriores).")
    ap.add_argument("--paralelismo", type=int, default=PARALELISMO,
                    help="Workers do pool (jobs e chunks). 0 = ILIMITADO (default; confia no backoff de 429/5xx); 1 = sequencial; >1 = teto manual.")
    ap.add_argument("--max-out-quant", type=int, default=0,
                    help="max_output_tokens da trilha quant (0 = default do modelo; ex.: 32768 p/ evitar MAX_TOKENS com thinking).")
    ap.add_argument("--modelos", default="",
                    help="Sobrescreve o set padrão por ids do REGISTRY, separados por vírgula (ex.: gemini-2.5-flash,deepseek-chat).")
    args = ap.parse_args()

    REFORCO = args.reforco
    TAG = args.tag
    PARALELISMO = args.paralelismo  # <=0 = ilimitado; 1 = sequencial; >1 = teto manual
    MAX_OUT_QUANT = max(0, args.max_out_quant)
    if args.modelos:
        ids = [s.strip() for s in args.modelos.split(",") if s.strip()]
        faltando = [i for i in ids if i not in REGISTRY]
        if faltando:
            raise SystemExit(f"Modelos fora do REGISTRY: {faltando}. Disponíveis: {list(REGISTRY)}")
        MODELOS = [REGISTRY[i] for i in ids]
    if args.thinking is not None:
        THINKING_OVERRIDE = int(args.thinking)
    if args.apenas_modelo:
        MODELOS = [m for m in MODELOS if m["id"] == args.apenas_modelo]
        if not MODELOS:
            raise SystemExit(f"Modelo não encontrado em MODELOS: {args.apenas_modelo}")

    if args.listar_modelos:
        log("Modelos disponíveis na conta:")
        for m in CLIENT.models.list():
            print("  ", getattr(m, "name", m))
        return

    pasta = Path(args.pasta)
    if not pasta.exists():
        raise SystemExit(f"Pasta não encontrada: {pasta}")

    filtros = [s.strip() for s in args.arquivos.split(",") if s.strip()]
    arquivos = selecionar_arquivos(pasta, filtros, args.limite)
    if not arquivos:
        raise SystemExit("Nenhum PDF selecionado (confira --arquivos / --limite / pasta).")

    log(f"Selecionados {len(arquivos)} arquivo(s):")
    for n, c in arquivos:
        log(f"  - {n} ({len(c) / 1024:,.0f} KB)")

    if args.dry_run:
        dry_run(arquivos, args.cnpj, args.modo)
        return

    executar(arquivos, args.cnpj, args.modo)


if __name__ == "__main__":
    main()
