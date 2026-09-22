"""
Script: servico_docling.py
Descrição: Serviço de conversão de documentos NÃO-PDF para Markdown via Docling.

           DECISÃO DE ARQUITETURA (2026-09-21): todo documento que NÃO é PDF
           (DOCX, XLSX, PPTX, HTML, Markdown, CSV, MSG/e-mail, imagens, etc.) é
           convertido para Markdown pelo Docling. PDFs são tratados pelo
           `servico_ocr_jina` (Jina OCR). Este módulo NÃO deve receber PDFs — o
           roteamento por extensão é feito no `servico_ia_qualitativa`.

           O Docling roda 100% local. Para os formatos de escritório suportados
           aqui ele não precisa dos modelos pesados de layout/OCR (esses só são
           carregados no pipeline de PDF, que não usamos), então a conversão é
           rápida e barata.

Funções/Procedimentos:
- log_status(mensagem: str) -> None: Log formatado com timestamp.
- _emit_status(mensagem, status_callback) -> None: Emite status humano ao callback do orquestrador.
- _get_converter(): Instancia (lazy, singleton) o DocumentConverter do Docling.
- converter_documento(nome_arquivo, conteudo_em_bytes, status_callback) -> str | None: Converte bytes em Markdown.
"""

from __future__ import annotations

import io
import time
from typing import Callable

_CONVERTER = None


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


def _get_converter():
    """Cria o DocumentConverter uma única vez (import tardio: Docling é pesado)."""
    global _CONVERTER
    if _CONVERTER is None:
        from docling.document_converter import DocumentConverter

        _CONVERTER = DocumentConverter()
    return _CONVERTER


def converter_documento(
    nome_arquivo: str,
    conteudo_em_bytes: bytes,
    status_callback: Callable[[str], None] | None = None,
) -> str | None:
    """Converte um documento não-PDF em Markdown usando o Docling.

    Retorna o Markdown (sem cabeçalho de arquivo) ou None em caso de falha.
    """
    from docling.datamodel.base_models import DocumentStream

    log_status(f"    [docling] Convertendo {nome_arquivo} para Markdown...")
    _emit_status(
        f"Convertendo {nome_arquivo} para Markdown com o Docling.",
        status_callback,
    )
    try:
        origem = DocumentStream(name=nome_arquivo, stream=io.BytesIO(conteudo_em_bytes))
        resultado = _get_converter().convert(origem)
        markdown = (resultado.document.export_to_markdown() or "").strip()
        return markdown or None
    except Exception as exc:
        log_status(f"    [docling] Falha ao converter {nome_arquivo}: {exc}")
        return None
