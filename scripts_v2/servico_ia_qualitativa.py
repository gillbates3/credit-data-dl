"""
Script: servico_ia_qualitativa.py
Descrição: Serviço qualitativo de conversão de documentos para Markdown fiel, usado
           como fonte de verdade para o modelo de análise de crédito (reasoning).

           DECISÃO DE ARQUITETURA (2026-09-21) — roteamento por tipo de arquivo:
             - PDF        -> `servico_ocr_jina` (Jina OCR, modelo jina-ocr-v1).
                             TODO PDF passa por OCR (digital ou escaneado), gerando
                             Markdown com tabelas em HTML. Fallback: texto digital
                             bruto (pdfplumber) e, por fim, placeholder.
             - NÃO-PDF    -> `servico_docling` (DOCX, XLSX, PPTX, HTML, CSV, MSG...).
                             Fallback: placeholder.
           Substitui a antiga trilha Gemini (texto por lotes / Vision) para a
           conversão de PDFs. O Gemini permanece apenas para gerar o TÍTULO
           descritivo do documento a partir do Markdown já extraído.

           A garantia de "nunca salvar vazio" (ver plano markdown-todos-pdfs) é
           mantida: sempre retornamos um bloco Markdown (conteúdo, texto bruto ou
           placeholder) com o modo correspondente.

Funções/Procedimentos:
- log_status(mensagem: str) -> None: Imprime mensagens de log formatadas com timestamp atual.
- calcular_md5(conteudo_em_bytes: bytes) -> str: Calcula a assinatura MD5 de dados em bytes.
- gerar_titulo_documento(cnpj, nome_arquivo, markdown) -> str: Gera um título descritivo (Gemini) a partir do Markdown.
- is_mostly_punctuation / strip_corrupted_runs / should_drop_input_line / sanitize_extracted_text: limpeza do texto bruto de fallback.
- parse_frontmatter / render_frontmatter / _quote_yaml / _unquote_yaml: manifesto YAML incremental por hash.
- extract_full_text_from_bytes(conteudo_em_bytes, nome_arquivo) -> tuple[str, bool]: texto digital do PDF (fallback) + flag escaneado.
- montar_bloco_markdown(nome_arquivo, markdown) -> str: envelopa o Markdown com o cabeçalho do arquivo, preservando tabelas.
- extrair_markdown_documento(cnpj, nome_arquivo, conteudo_em_bytes, status_callback) -> tuple[str, str]: dispatcher por extensão (PDF->Jina; resto->Docling), com fallback garantido.
- extrair_dados_qualitativos(cnpj, arquivos_em_memoria, markdown_existente, incluir_frontmatter) -> str: orquestração incremental por hash (usada pelo CLI de teste).
- carregar_arquivos_em_memoria(pasta_base) -> list[tuple[str, bytes]]: lê documentos suportados do disco para a memória.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import time
from pathlib import Path
from typing import Callable

import pdfplumber
from dotenv import load_dotenv
from google import genai
from google.genai import types

try:
    from scripts_v2 import servico_docling, servico_ocr_jina
except ImportError:  # execução direta a partir de scripts_v2/
    import servico_docling
    import servico_ocr_jina

SCRIPT_DIR = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
DEBUG_FILE = SCRIPT_DIR / "debug_qualitativo.md"

load_dotenv(PROJETO_RAIZ / ".env.local")
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY não encontrada no .env.local.")

# O Gemini é usado apenas para gerar títulos descritivos a partir do Markdown já
# extraído. A conversão de documentos é feita por Jina OCR (PDF) e Docling (resto).
CLIENT = genai.Client(api_key=API_KEY)
MODEL_NAME = "gemini-2.5-flash"

MIN_TEXT_CHARS_PER_PAGE = 60
EXTENSOES_PDF = {".pdf"}
# Formatos que o Docling converte bem (não-PDF). Usado só pelo CLI de teste.
EXTENSOES_SUPORTADAS = {
    ".pdf", ".docx", ".xlsx", ".pptx", ".html", ".htm",
    ".md", ".markdown", ".csv", ".msg", ".png", ".jpg", ".jpeg", ".tiff",
}

PROMPT_TITULO = """
Você gera títulos descritivos para documentos corporativos em pt-BR.

Retorne somente uma linha, sem aspas, sem markdown e sem extensão de arquivo.
O título deve ser conciso, preferencialmente com até 60 caracteres.
Use o padrão:
<Tipo do documento> [<emissão/série/identificador, se houver>] <Período abreviado>

Regras:
- Priorize termos como ITR, DFP, Demonstrações Financeiras, Escritura, Rating e Release de Resultados quando o conteúdo indicar isso.
- O período abreviado deve ser algo como Dez2025, Mar2026, 3T2025 ou outro intervalo curto claramente suportado pelo conteúdo.
- Inclua emissão, série ou identificador somente se estiver explícito e for útil.
- Não invente dados ausentes ou incertos.
- Se a confiança for baixa, retorne um título neutro como Documento <data se houver>.
""".strip()


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


def gerar_titulo_documento(cnpj: str, nome_arquivo: str, markdown: str) -> str:
    """Gera um título descritivo a partir do conteúdo do documento (via Gemini)."""
    fallback = Path(nome_arquivo).stem or nome_arquivo or "Documento"
    trecho = (markdown or "").strip()[:6000]
    if not trecho:
        return fallback

    prompt = (
        f"{PROMPT_TITULO}\n\n"
        f"CNPJ: {cnpj}\n"
        f"Arquivo: {nome_arquivo}\n\n"
        f"Conteúdo (início):\n{trecho}"
    )
    try:
        response = CLIENT.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0),
        )
        bruto = (response.text or "").strip()
        titulo = (
            bruto.splitlines()[0].strip().strip('"').strip("'").strip("#").strip()
            if bruto
            else ""
        )
        titulo = re.sub(r"\s+", " ", titulo).strip()
        return titulo[:80] if titulo else fallback
    except Exception as e:
        log_status(f"[titulo] Falha ao gerar título para {nome_arquivo}: {e}. Usando fallback.")
        return fallback


def calcular_md5(conteudo_em_bytes: bytes) -> str:
    return hashlib.md5(conteudo_em_bytes).hexdigest()


def is_mostly_punctuation(texto: str) -> bool:
    base = texto.strip()
    if not base:
        return False
    punctuation_chars = sum(1 for ch in base if not ch.isalnum() and not ch.isspace())
    return (punctuation_chars / max(len(base), 1)) >= 0.6


def strip_corrupted_runs(line: str) -> str:
    cleaned = re.sub(r"\.{8,}.*$", "", line).rstrip()
    cleaned = re.sub(r"-{8,}.*$", "", cleaned).rstrip()
    return cleaned


def should_drop_input_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if re.fullmatch(r"[.\-_ ]{8,}", stripped):
        return True
    if len(stripped) > 200 and is_mostly_punctuation(stripped):
        return True
    if "........" in stripped:
        return True
    return False


def sanitize_extracted_text(text: str) -> tuple[str, int]:
    sanitized_lines = []
    removed = 0
    for line in text.splitlines():
        candidate = strip_corrupted_runs(line)
        if should_drop_input_line(candidate):
            removed += 1
            continue
        sanitized_lines.append(candidate.rstrip())

    collapsed = []
    previous_blank = False
    for line in sanitized_lines:
        blank = not line.strip()
        if blank and previous_blank:
            continue
        collapsed.append(line)
        previous_blank = blank

    return "\n".join(collapsed).strip(), removed


def parse_frontmatter(markdown_existente: str) -> tuple[list[dict], str]:
    if not markdown_existente.startswith("---\n"):
        return [], markdown_existente

    fechamento = markdown_existente.find("\n---\n", 4)
    if fechamento == -1:
        return [], markdown_existente

    frontmatter = markdown_existente[4:fechamento]
    corpo = markdown_existente[fechamento + 5 :]
    linhas = [linha.rstrip() for linha in frontmatter.splitlines()]

    if not linhas or linhas[0].strip() != "arquivos_processados:":
        return [], markdown_existente

    arquivos = []
    atual = None
    for linha in linhas[1:]:
        if re.match(r"^\s*-\s+nome_arquivo:\s+", linha):
            valor = linha.split(":", 1)[1].strip()
            atual = {"nome_arquivo": _unquote_yaml(valor), "hash_md5": ""}
            arquivos.append(atual)
            continue
        if atual is not None and re.match(r"^\s+hash_md5:\s+", linha):
            valor = linha.split(":", 1)[1].strip()
            atual["hash_md5"] = _unquote_yaml(valor)

    arquivos_validos = [item for item in arquivos if item.get("hash_md5")]
    return arquivos_validos, corpo.lstrip("\n")


def _quote_yaml(valor: str) -> str:
    escaped = valor.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _unquote_yaml(valor: str) -> str:
    valor = valor.strip()
    if len(valor) >= 2 and valor[0] == '"' and valor[-1] == '"':
        valor = valor[1:-1]
        valor = valor.replace('\\"', '"').replace("\\\\", "\\")
    return valor


def render_frontmatter(arquivos_processados: list[dict], corpo: str) -> str:
    linhas = ["---", "arquivos_processados:"]
    for item in arquivos_processados:
        linhas.append(f"  - nome_arquivo: {_quote_yaml(item['nome_arquivo'])}")
        linhas.append(f"    hash_md5: {_quote_yaml(item['hash_md5'])}")
    linhas.append("---")
    linhas.append("")
    texto_corpo = corpo.lstrip("\n")
    return "\n".join(linhas) + texto_corpo


def extract_full_text_from_bytes(conteudo_em_bytes: bytes, nome_arquivo: str) -> tuple[str, bool]:
    text_parts = []
    total_pages = 0
    pages_with_text = 0

    try:
        with pdfplumber.open(io.BytesIO(conteudo_em_bytes)) as pdf:
            total_pages = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                text = (page.extract_text() or "").strip()
                if len(text) >= MIN_TEXT_CHARS_PER_PAGE:
                    pages_with_text += 1
                    text_parts.append(f"\n\n--- PÁGINA {i + 1} ---\n{text}")
    except Exception as e:
        print(f"    [pdfplumber] Erro ao abrir {nome_arquivo}: {e}")
        return "", True

    is_scanned = total_pages > 0 and pages_with_text < (total_pages * 0.1)
    raw_text = "".join(text_parts).strip()
    sanitized_text, removed_lines = sanitize_extracted_text(raw_text)
    if removed_lines:
        log_status(f"    [Sanitizacao] {removed_lines} linha(s) ruidosa(s) removida(s) do texto extraído de {nome_arquivo}.")
    return sanitized_text, is_scanned


def montar_bloco_markdown(nome_arquivo: str, markdown: str) -> str:
    """Envelopa o Markdown com o cabeçalho do arquivo, preservando tabelas.

    Diferente da era Gemini (que proibia tabelas com pipes), Jina e Docling geram
    tabelas (HTML e Markdown, respectivamente); por isso NÃO aplicamos aqui a
    remoção agressiva de linhas de tabela — apenas colapsamos linhas em branco em
    excesso.
    """
    conteudo = (markdown or "").strip()
    if not conteudo:
        return ""
    conteudo = re.sub(r"\n{3,}", "\n\n", conteudo)
    return f"\n\n# {nome_arquivo}\n\n{conteudo}\n"


def _extrair_markdown_pdf(
    nome_arquivo: str,
    conteudo_em_bytes: bytes,
    status_callback: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """PDF -> Jina OCR. Fallback: texto digital bruto -> placeholder."""
    markdown_bruto = servico_ocr_jina.ocr_pdf(
        nome_arquivo,
        conteudo_em_bytes,
        status_callback=status_callback,
    )
    if markdown_bruto:
        bloco = montar_bloco_markdown(nome_arquivo, markdown_bruto)
        if bloco.strip():
            _emit_status(f"OCR concluído para {nome_arquivo}.", status_callback)
            return bloco.strip(), "jina"

    texto, _ = extract_full_text_from_bytes(conteudo_em_bytes, nome_arquivo)
    if texto.strip():
        log_status(f"[qualitativo] Jina OCR falhou; fallback para texto bruto em {nome_arquivo}.")
        _emit_status(
            f"Jina OCR falhou; salvando texto digital bruto de {nome_arquivo}.",
            status_callback,
        )
        return (
            f"# {nome_arquivo}\n\n"
            "> _Transcrição automática (texto bruto; o Jina OCR não retornou markdown)._\n\n"
            f"{texto.strip()}",
            "texto_bruto",
        )

    log_status(f"[qualitativo] Fallback para placeholder em {nome_arquivo}.")
    _emit_status(
        f"Não foi possível extrair conteúdo de {nome_arquivo}; salvando placeholder.",
        status_callback,
    )
    return (
        f"# {nome_arquivo}\n\n"
        "> _Não foi possível extrair conteúdo deste PDF (Jina OCR falhou). Reenvie com `force` para reprocessar._",
        "placeholder",
    )


def _extrair_markdown_nao_pdf(
    nome_arquivo: str,
    conteudo_em_bytes: bytes,
    status_callback: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """Não-PDF -> Docling. Fallback: placeholder."""
    markdown_bruto = servico_docling.converter_documento(
        nome_arquivo,
        conteudo_em_bytes,
        status_callback=status_callback,
    )
    if markdown_bruto:
        bloco = montar_bloco_markdown(nome_arquivo, markdown_bruto)
        if bloco.strip():
            _emit_status(f"Conversão concluída para {nome_arquivo}.", status_callback)
            return bloco.strip(), "docling"

    log_status(f"[qualitativo] Docling não retornou conteúdo para {nome_arquivo}.")
    _emit_status(
        f"Não foi possível converter {nome_arquivo}; salvando placeholder.",
        status_callback,
    )
    return (
        f"# {nome_arquivo}\n\n"
        "> _Não foi possível converter este documento para Markdown (Docling falhou). Reenvie com `force` para reprocessar._",
        "placeholder",
    )


def extrair_markdown_documento(
    cnpj: str,
    nome_arquivo: str,
    conteudo_em_bytes: bytes,
    status_callback: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """Dispatcher por extensão: PDF -> Jina OCR; demais formatos -> Docling.

    Retorna sempre (markdown, modo), com modo ∈
    {"jina", "docling", "texto_bruto", "placeholder"}. `cnpj` é mantido na
    assinatura por compatibilidade com o orquestrador (uso futuro/log).
    """
    extensao = Path(nome_arquivo).suffix.lower()
    if extensao in EXTENSOES_PDF:
        return _extrair_markdown_pdf(nome_arquivo, conteudo_em_bytes, status_callback)
    return _extrair_markdown_nao_pdf(nome_arquivo, conteudo_em_bytes, status_callback)


def extrair_dados_qualitativos(
    cnpj: str,
    arquivos_em_memoria: list[tuple[str, bytes]],
    markdown_existente: str = "",
    incluir_frontmatter: bool = True,
) -> str:
    arquivos_processados, corpo_existente = parse_frontmatter(markdown_existente or "")
    hashes_processados = {item["hash_md5"] for item in arquivos_processados if item.get("hash_md5")}
    corpo = corpo_existente.rstrip()
    total_arquivos = len(arquivos_em_memoria)

    log_status(f"[qualitativo] Iniciando processamento de {total_arquivos} arquivo(s) para o CNPJ {cnpj}.")
    if arquivos_processados:
        log_status(f"[qualitativo] Estado inicial contém {len(arquivos_processados)} hash(es) já processado(s).")

    for indice, (nome_arquivo, conteudo_em_bytes) in enumerate(arquivos_em_memoria, start=1):
        inicio_arquivo = time.time()
        try:
            hash_md5 = calcular_md5(conteudo_em_bytes)
            if hash_md5 in hashes_processados:
                log_status(f"[qualitativo] [{indice}/{total_arquivos}] Pulado por hash já processado: {nome_arquivo}")
                continue

            tamanho_kb = len(conteudo_em_bytes) / 1024
            log_status(
                f"[qualitativo] [{indice}/{total_arquivos}] Analisando {nome_arquivo} "
                f"({tamanho_kb:,.1f} KB | md5={hash_md5[:12]}...)"
            )

            bloco, modo = extrair_markdown_documento(cnpj, nome_arquivo, conteudo_em_bytes)
            if not bloco:
                duracao = time.time() - inicio_arquivo
                log_status(f"[qualitativo] [{indice}/{total_arquivos}] Falha: nenhum Markdown válido extraído de {nome_arquivo} após {duracao:.1f}s.")
                continue

            corpo = f"{corpo}\n{bloco}".rstrip() if corpo else bloco
            arquivos_processados.append({"nome_arquivo": nome_arquivo, "hash_md5": hash_md5})
            hashes_processados.add(hash_md5)
            duracao = time.time() - inicio_arquivo
            log_status(
                f"[qualitativo] [{indice}/{total_arquivos}] Sucesso ({modo}): Markdown anexado para {nome_arquivo} "
                f"em {duracao:.1f}s."
            )
        except Exception as e:
            duracao = time.time() - inicio_arquivo
            log_status(f"[qualitativo] [{indice}/{total_arquivos}] Erro ao processar {nome_arquivo} após {duracao:.1f}s: {e}")
            continue

    log_status(
        f"[qualitativo] Processamento concluído. Total acumulado no manifesto: "
        f"{len(arquivos_processados)} arquivo(s)."
    )
    if not incluir_frontmatter:
        return (corpo + "\n").lstrip("\n") if corpo else ""
    return render_frontmatter(arquivos_processados, corpo + ("\n" if corpo else ""))


def carregar_arquivos_em_memoria(pasta_base: Path) -> list[tuple[str, bytes]]:
    arquivos = []
    caminhos = sorted(
        p for p in pasta_base.rglob("*")
        if p.is_file() and p.suffix.lower() in EXTENSOES_SUPORTADAS
    )
    log_status(f"[debug] Procurando documentos suportados recursivamente em: {pasta_base}")
    log_status(f"[debug] {len(caminhos)} documento(s) encontrado(s).")
    for indice, path in enumerate(caminhos, start=1):
        try:
            with open(path, "rb") as f:
                conteudo = f.read()
            tamanho_kb = len(conteudo) / 1024
            log_status(f"[debug] [{indice}/{len(caminhos)}] Carregado em memória: {path} ({tamanho_kb:,.1f} KB)")
            arquivos.append((path.name, conteudo))
        except Exception as e:
            log_status(f"[debug] Falha ao ler {path}: {e}")
    return arquivos


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Módulo de IA Qualitativa - documentos em memória")
    parser.add_argument("pasta_base", help="Pasta com documentos de teste")
    parser.add_argument("--cnpj", default="00000000000000", help="CNPJ para o teste local")
    args = parser.parse_args()

    pasta_base = Path(args.pasta_base)
    if not pasta_base.exists():
        raise SystemExit(f"Pasta não encontrada: {pasta_base}")

    inicio_total = time.time()
    log_status("=" * 72)
    log_status("TESTE LOCAL - SERVIÇO DE CONVERSÃO QUALITATIVA")
    log_status(f"Pasta base: {pasta_base}")
    log_status(f"CNPJ informado: {args.cnpj}")
    log_status("Conversão: PDF -> Jina OCR (jina-ocr-v1) | não-PDF -> Docling")
    log_status("Fluxo: disco local -> bytes em memória -> função principal -> markdown final")
    log_status("=" * 72)

    arquivos_em_memoria = carregar_arquivos_em_memoria(pasta_base)
    if not arquivos_em_memoria:
        raise SystemExit("Nenhum documento suportado encontrado para teste.")

    total_bytes = sum(len(conteudo) for _, conteudo in arquivos_em_memoria)
    log_status(
        f"[debug] Iniciando chamada principal com {len(arquivos_em_memoria)} arquivo(s) "
        f"e {total_bytes / (1024 * 1024):.2f} MB em memória."
    )
    resultado = extrair_dados_qualitativos(args.cnpj, arquivos_em_memoria, markdown_existente="")
    with open(DEBUG_FILE, "w", encoding="utf-8") as f:
        f.write(resultado)
    duracao_total = time.time() - inicio_total
    log_status(f"[debug] Resultado salvo em: {DEBUG_FILE}")
    log_status(f"[debug] Tamanho do markdown final: {len(resultado):,} caracteres")
    log_status(f"[debug] Tempo total da execução: {duracao_total:.1f}s")
