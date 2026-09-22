"""
Script: servico_ocr_jina.py
Descrição: Serviço de OCR de PDFs via Jina AI (modelo `jina-ocr-v1`).

           DECISÃO DE ARQUITETURA (2026-09-21): TODO arquivo PDF é convertido para
           Markdown por este serviço. Cada página é rasterizada localmente
           (pypdfium2) e enviada ao endpoint OpenAI-compatible da Jina; o modelo
           jina-ocr-v1 devolve Markdown fiel (tabelas em HTML), sem necessidade de
           processamento pesado no servidor. Substitui a antiga trilha Gemini
           (texto por lotes / Vision) para PDFs. Documentos NÃO-PDF são convertidos
           pelo `servico_docling`.

           Como o Jina sempre rasteriza + OCR-iza a página, o mesmo caminho serve
           tanto para PDFs digitais quanto para PDFs escaneados (o "OCR quando
           necessário" acontece por padrão).

Funções/Procedimentos:
- log_status(mensagem: str) -> None: Log formatado com timestamp.
- _emit_status(mensagem, status_callback) -> None: Emite status humano ao callback do orquestrador.
- _render_pagina_png(pdf, indice, dpi) -> bytes: Rasteriza uma página do PDF em PNG.
- _chamar_jina(imagem_b64) -> str | None: Chama o endpoint jina-ocr-v1 com retry para 429/5xx.
- ocr_pdf(nome_arquivo, conteudo_em_bytes, status_callback) -> str | None: OCR-iza todas as páginas e concatena o Markdown.
"""

from __future__ import annotations

import base64
import io
import json
import os
import time
from pathlib import Path
from typing import Callable

import pypdfium2 as pdfium
import requests
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent

# A chave da Jina costuma estar no .env (a raiz) e não no .env.local dos serviços.
load_dotenv(PROJETO_RAIZ / ".env.local")
load_dotenv(PROJETO_RAIZ / ".env")

JINA_URL = "https://api.jina.ai/v1/chat/completions"
JINA_MODEL = "jina-ocr-v1"
RENDER_DPI = 150
MAX_TENTATIVAS = 6
TIMEOUT_S = 600

PROMPT_OCR = (
    "Transcribe this document page into clean, faithful Markdown. "
    "Preserve every number, percentage and value EXACTLY as printed. "
    "Render tables as HTML tables (<table>...</table>) keeping the exact cell values. "
    "Do not summarize, translate or invent content. "
    "Return only the Markdown, without code fences or comments."
)


def log_status(mensagem: str) -> None:
    agora = time.strftime("%H:%M:%S")
    print(f"[{agora}] {mensagem}")


def _emit_status(
    mensagem: str,
    status_callback: Callable[[str], None] | None = None,
) -> None:
    if not status_callback:
        return
    try:
        status_callback(" ".join(mensagem.split()))
    except Exception:
        pass


def _get_api_key() -> str:
    chave = os.getenv("JINA_API_KEY")
    if not chave:
        raise RuntimeError(
            "JINA_API_KEY não encontrada. Configure-a no .env (ou .env.local) da raiz do projeto."
        )
    return chave


def _render_pagina_png(pdf: "pdfium.PdfDocument", indice: int, dpi: int = RENDER_DPI) -> bytes:
    imagem = pdf[indice].render(scale=dpi / 72).to_pil()
    buffer = io.BytesIO()
    imagem.save(buffer, format="PNG")
    return buffer.getvalue()


def _chamar_jina(imagem_b64: str) -> str | None:
    chave = _get_api_key()
    corpo = {
        "model": JINA_MODEL,
        "max_tokens": 8192,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + imagem_b64},
                    },
                    {"type": "text", "text": PROMPT_OCR},
                ],
            }
        ],
    }
    cabecalhos = {
        "Authorization": "Bearer " + chave,
        "Content-Type": "application/json",
    }

    for tentativa in range(MAX_TENTATIVAS):
        try:
            resposta = requests.post(
                JINA_URL,
                headers=cabecalhos,
                data=json.dumps(corpo),
                timeout=TIMEOUT_S,
            )
            if resposta.status_code == 200:
                dados = resposta.json()
                return (dados["choices"][0]["message"]["content"] or "").strip()
            if resposta.status_code in (429, 500, 502, 503, 504):
                espera = 8 + tentativa * 4
                log_status(
                    f"    [jina] HTTP {resposta.status_code}. Aguardando {espera}s e tentando novamente..."
                )
                time.sleep(espera)
                continue
            # Erro definitivo (400/401/403/...): não adianta repetir.
            log_status(f"    [jina] HTTP {resposta.status_code}: {resposta.text[:200]}")
            return None
        except Exception as exc:  # timeout, conexão, etc.
            espera = 8 + tentativa * 4
            log_status(
                f"    [jina] Erro de rede ({type(exc).__name__}). Aguardando {espera}s..."
            )
            time.sleep(espera)
    return None


def ocr_pdf(
    nome_arquivo: str,
    conteudo_em_bytes: bytes,
    status_callback: Callable[[str], None] | None = None,
) -> str | None:
    """OCR-iza todas as páginas do PDF via jina-ocr-v1 e concatena o Markdown.

    Retorna o Markdown (sem cabeçalho de arquivo) ou None se nenhuma página
    tiver sido convertida com sucesso.
    """
    try:
        pdf = pdfium.PdfDocument(conteudo_em_bytes)
    except Exception as exc:
        log_status(f"    [jina] Falha ao abrir PDF {nome_arquivo}: {exc}")
        return None

    total_paginas = len(pdf)
    if total_paginas == 0:
        log_status(f"    [jina] PDF sem páginas: {nome_arquivo}.")
        return None

    log_status(
        f"    [jina] OCR de {nome_arquivo}: {total_paginas} página(s) via {JINA_MODEL}."
    )
    _emit_status(
        f"PDF com {total_paginas} página(s). Enviando ao Jina OCR ({JINA_MODEL}).",
        status_callback,
    )

    partes: list[str] = []
    falhas = 0
    for indice in range(total_paginas):
        _emit_status(
            f"OCR da página {indice + 1} de {total_paginas} de {nome_arquivo} no Jina.",
            status_callback,
        )
        try:
            imagem_b64 = base64.b64encode(_render_pagina_png(pdf, indice)).decode()
        except Exception as exc:
            log_status(f"    [jina] Falha ao rasterizar página {indice + 1} de {nome_arquivo}: {exc}")
            falhas += 1
            continue

        conteudo = _chamar_jina(imagem_b64)
        if conteudo:
            partes.append(conteudo)
            log_status(f"    [jina] {nome_arquivo} página {indice + 1}/{total_paginas} OK.")
        else:
            falhas += 1
            log_status(f"    [jina] {nome_arquivo} página {indice + 1}/{total_paginas} sem retorno.")

    if not partes:
        return None
    if falhas:
        log_status(
            f"    [jina] {nome_arquivo}: {falhas} página(s) sem retorno de {total_paginas}."
        )
    return "\n\n".join(partes).strip() or None
