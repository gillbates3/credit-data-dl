import argparse
import hashlib
import io
import os
import re
import tempfile
import time
from pathlib import Path

import pdfplumber
from dotenv import load_dotenv
from google import genai
from google.genai import types

SCRIPT_DIR = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
DEBUG_FILE = SCRIPT_DIR / "debug_qualitativo.md"

load_dotenv(PROJETO_RAIZ / ".env.local")
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY não encontrada no .env.local.")

CLIENT = genai.Client(api_key=API_KEY)
MODEL_NAME = "gemini-2.5-flash"

MIN_TEXT_CHARS_PER_PAGE = 60
MAX_VISION_RETRIES = 3
MAX_OUTPUT_LINE_LENGTH = 1200
PROMPT_QUALITATIVO = """
Você é um Especialista Sênior em Extração de Dados Financeiros e Transcrição de Documentos Corporativos.

Sua tarefa é ler o documento fornecido (demonstrações financeiras, relatórios de rating, apresentações de resultados, etc.) e convertê-lo em um texto Markdown ALTAMENTE DETALHADO E FIDEDIGNO.

OBJETIVO PRINCIPAL:
Este conteúdo em Markdown servirá como a ÚNICA fonte de verdade qualitativa e quantitativa para um modelo de análise de crédito futuro. Portanto, a regra de ouro é: NÃO RESUMA SINTETICAMENTE. PRESERVE A DENSIDADE DA INFORMAÇÃO.

REGRAS DE EXTRAÇÃO:
1. PRESERVAÇÃO DE DADOS: Extraia todos os dados numéricos, percentuais, metas, covenants, prazos e valores financeiros mencionados no texto. Preserve a exatidão de todos os dados.
2. PRESERVAÇÃO DE NARRATIVA: Mantenha as explicações da diretoria, comentários sobre performance operacional, justificativas de aumentos de custos, riscos de mercado listados e estratégias futuras. Não corte os argumentos do emissor.
3. ESTRUTURAÇÃO MANTIDA: Tente replicar a estrutura do documento original usando os cabeçalhos do Markdown (#, ##, ###). Se o PDF tem uma seção "Análise de Endividamento", crie um `## Análise de Endividamento` e preserve o conteúdo nela.
4. TABELAS DE DADOS: NÃO tente reconstruir tabelas visuais complexas usando pipes do Markdown (`| Coluna |`). Em vez disso, transcreva tabelas e quadros em FORMATO TEXTO ESTRUTURADO, preservando rótulos, períodos e valores. Use listas, subtópicos e pares "campo: valor". Se necessário, organize assim:
   - Linha/Item: nome da linha
   - Coluna 1: valor
   - Coluna 2: valor
   - Observação: texto
5. FIDELIDADE ACIMA DE BELEZA: Priorize preservar corretamente os números e o sentido econômico do trecho, mesmo que a formatação fique menos elegante. É melhor uma tabela virar um bloco textual estruturado do que gerar uma tabela Markdown quebrada, truncada ou preenchida com sequências como `.....` ou `-----`.
6. O QUE VOCÊ PODE IGNORAR: Você tem permissão para pular e ignorar estritamente: capas, índices, textos padronizados de isenção de responsabilidade legal ("forward-looking statements"), notas de rodapé irrelevantes e cabeçalhos/rodapés de páginas repetitivos. Todo o resto ligado ao negócio e finanças deve ser transcrito e estruturado.

FORMATO DE SAÍDA:
- O formato de saída deve ser estritamente em Markdown.
- Não adicione saudações ou explicações no início ou no fim.
- Retorne apenas o conteúdo extraído e estruturado como TEXTO Markdown.
- Não use tabelas Markdown com pipes para quadros complexos.
- Para dados tabulares, use blocos textuais estruturados, listas e subtópicos.
""".strip()


def log_status(mensagem: str) -> None:
    agora = time.strftime("%H:%M:%S")
    print(f"[{agora}] {mensagem}")


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


def sanitize_generated_markdown(markdown_text: str) -> tuple[str, int]:
    sanitized_lines = []
    removed = 0

    for line in markdown_text.splitlines():
        candidate = strip_corrupted_runs(line)
        stripped = candidate.strip()

        if len(line) > MAX_OUTPUT_LINE_LENGTH:
            if stripped.startswith("|") and is_mostly_punctuation(line):
                removed += 1
                continue
            if is_mostly_punctuation(line):
                removed += 1
                continue

        if stripped.startswith("|") and re.search(r"[-.]{20,}", line):
            removed += 1
            continue

        if re.fullmatch(r"[.\-_|: ]{8,}", stripped):
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


def get_model_qualitativo():
    return types.GenerateContentConfig(temperature=0.0)


def call_ai_with_text(config, cnpj: str, nome_arquivo: str, text: str) -> str | None:
    prompt = (
        f"CNPJ: {cnpj}\n"
        f"Arquivo: {nome_arquivo}\n\n"
        f"{PROMPT_QUALITATIVO}\n\n"
        "Texto extraído do PDF:\n"
        f"{text}"
    )
    try:
        log_status(f"[IA-texto] Aguardando resposta do Gemini para {nome_arquivo}...")
        response = CLIENT.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=config,
        )
        return (response.text or "").strip()
    except Exception as e:
        print(f"    [IA-texto] Erro em {nome_arquivo}: {e}")
        return None


def file_state_name(file_info) -> str:
    state = getattr(file_info, "state", None)
    if hasattr(state, "name"):
        return state.name
    return str(state or "")


def call_ai_with_pdf_vision(config, cnpj: str, nome_arquivo: str, conteudo_em_bytes: bytes) -> str | None:
    for attempt in range(MAX_VISION_RETRIES):
        uploaded = None
        temp_path = None
        try:
            suffix = Path(nome_arquivo).suffix or ".pdf"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(conteudo_em_bytes)
                temp_path = tmp.name

            log_status(f"    [Vision] Tentativa {attempt + 1}/{MAX_VISION_RETRIES}: preparando upload de {nome_arquivo}...")
            uploaded = CLIENT.files.upload(file=temp_path)

            log_status(f"    [Vision] Upload concluído para {nome_arquivo}. Aguardando processamento remoto...")
            while True:
                file_info = CLIENT.files.get(name=uploaded.name)
                if file_state_name(file_info) == "PROCESSING":
                    log_status(f"    [Vision] Gemini ainda está processando {nome_arquivo}...")
                    time.sleep(2)
                    continue
                break

            if file_state_name(file_info) == "FAILED":
                print(f"    [Vision] Falha no processamento do {nome_arquivo}")
                return None

            prompt = (
                f"CNPJ: {cnpj}\n"
                f"Arquivo: {nome_arquivo}\n\n"
                f"{PROMPT_QUALITATIVO}"
            )
            log_status(f"    [Vision] Enviando prompt final ao Gemini para {nome_arquivo}...")
            response = CLIENT.models.generate_content(
                model=MODEL_NAME,
                contents=[prompt, file_info],
                config=config,
            )
            return (response.text or "").strip()
        except Exception as e:
            if "429" in str(e):
                wait_time = (attempt + 1) * 30
                print(f"    [Vision] Quota (429) em {nome_arquivo}. Aguardando {wait_time}s...")
                time.sleep(wait_time)
                continue
            print(f"    [Vision] Erro em {nome_arquivo}: {e}")
            return None
        finally:
            if uploaded is not None:
                try:
                    CLIENT.files.delete(name=uploaded.name)
                except Exception as delete_error:
                    print(f"    [Vision] Aviso ao limpar arquivo remoto {nome_arquivo}: {delete_error}")
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
    return None


def montar_bloco_markdown(nome_arquivo: str, markdown_pdf: str) -> str:
    conteudo, removed_lines = sanitize_generated_markdown(markdown_pdf.strip())
    if removed_lines:
        log_status(f"    [Sanitizacao] {removed_lines} linha(s) corrompida(s) removida(s) do Markdown de {nome_arquivo}.")
    if not conteudo:
        return ""
    return f"\n\n# {nome_arquivo}\n\n{conteudo}\n"


def extrair_dados_qualitativos(
    cnpj: str,
    arquivos_em_memoria: list[tuple[str, bytes]],
    markdown_existente: str = "",
) -> str:
    arquivos_processados, corpo_existente = parse_frontmatter(markdown_existente or "")
    hashes_processados = {item["hash_md5"] for item in arquivos_processados if item.get("hash_md5")}
    corpo = corpo_existente.rstrip()
    config = get_model_qualitativo()
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
            log_status(f"[qualitativo] [{indice}/{total_arquivos}] Extraindo texto do PDF em memória...")
            texto_extraido, is_scanned = extract_full_text_from_bytes(conteudo_em_bytes, nome_arquivo)

            markdown_pdf = None
            if texto_extraido and not is_scanned:
                char_count = len(texto_extraido)
                estimated_tokens = char_count // 4
                log_status(
                    f"[qualitativo] [{indice}/{total_arquivos}] Texto extraído com {char_count:,} chars "
                    f"(~{estimated_tokens:,} tokens). Usando modo Texto."
                )
                markdown_pdf = call_ai_with_text(config, cnpj, nome_arquivo, texto_extraido)
                if not markdown_pdf:
                    log_status(f"[qualitativo] [{indice}/{total_arquivos}] Fallback Texto→Vision para {nome_arquivo}.")
                    markdown_pdf = call_ai_with_pdf_vision(config, cnpj, nome_arquivo, conteudo_em_bytes)
            else:
                log_status(
                    f"[qualitativo] [{indice}/{total_arquivos}] PDF sem texto útil suficiente. "
                    f"Usando modo Vision."
                )
                markdown_pdf = call_ai_with_pdf_vision(config, cnpj, nome_arquivo, conteudo_em_bytes)

            if not markdown_pdf:
                duracao = time.time() - inicio_arquivo
                log_status(f"[qualitativo] [{indice}/{total_arquivos}] Falha: nenhum Markdown válido extraído de {nome_arquivo} após {duracao:.1f}s.")
                continue

            bloco = montar_bloco_markdown(nome_arquivo, markdown_pdf)
            if not bloco:
                duracao = time.time() - inicio_arquivo
                log_status(f"[qualitativo] [{indice}/{total_arquivos}] Falha: conteúdo vazio retornado para {nome_arquivo} após {duracao:.1f}s.")
                continue

            corpo = f"{corpo}\n{bloco.lstrip()}".rstrip() if corpo else bloco.strip()
            arquivos_processados.append({"nome_arquivo": nome_arquivo, "hash_md5": hash_md5})
            hashes_processados.add(hash_md5)
            duracao = time.time() - inicio_arquivo
            log_status(
                f"[qualitativo] [{indice}/{total_arquivos}] Sucesso: Markdown anexado para {nome_arquivo} "
                f"em {duracao:.1f}s."
            )
            time.sleep(1)
        except Exception as e:
            duracao = time.time() - inicio_arquivo
            log_status(f"[qualitativo] [{indice}/{total_arquivos}] Erro ao processar {nome_arquivo} após {duracao:.1f}s: {e}")
            continue

    log_status(
        f"[qualitativo] Processamento concluído. Total acumulado no manifesto: "
        f"{len(arquivos_processados)} arquivo(s)."
    )
    return render_frontmatter(arquivos_processados, corpo + ("\n" if corpo else ""))


def carregar_arquivos_em_memoria(pasta_base: Path) -> list[tuple[str, bytes]]:
    arquivos = []
    caminhos = sorted(pasta_base.rglob("*.pdf"))
    log_status(f"[debug] Procurando PDFs recursivamente em: {pasta_base}")
    log_status(f"[debug] {len(caminhos)} PDF(s) encontrado(s).")
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
    parser = argparse.ArgumentParser(description="Módulo de IA Qualitativa - PDFs em memória")
    parser.add_argument("pasta_base", help="Pasta com PDFs de teste")
    parser.add_argument("--cnpj", default="00000000000000", help="CNPJ para o teste local")
    args = parser.parse_args()

    pasta_base = Path(args.pasta_base)
    if not pasta_base.exists():
        raise SystemExit(f"Pasta não encontrada: {pasta_base}")

    inicio_total = time.time()
    log_status("=" * 72)
    log_status("TESTE LOCAL - SERVIÇO DE IA QUALITATIVA")
    log_status(f"Pasta base: {pasta_base}")
    log_status(f"CNPJ informado: {args.cnpj}")
    log_status(f"Modelo Gemini: {MODEL_NAME}")
    log_status("Fluxo: disco local -> bytes em memória -> função principal -> markdown final")
    log_status("=" * 72)

    arquivos_em_memoria = carregar_arquivos_em_memoria(pasta_base)
    if not arquivos_em_memoria:
        raise SystemExit("Nenhum PDF encontrado para teste.")

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
