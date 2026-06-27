"""
Script: servico_ia_quantitativa.py
Descrição: Serviço quantitativo baseado em LLM (Gemini) para extração de demonstrações financeiras
           e geração estruturada de JSONs (padrão CVM) a partir de PDFs contidos em memória RAM.
           Implementa um sistema incremental por hash MD5 para skips automáticos de arquivos já processados.

Funções/Procedimentos:
- log_status(mensagem: str) -> None: Imprime mensagens de log formatadas com timestamp atual.
- system_instruction_quantitativa(existing_periods: list[str]) -> str: Retorna a instrução do sistema quantitativa com períodos existentes.
- get_generation_config_quantitativo(periodos_existentes: list[str] | None = None): Retorna as configurações de geração estruturada em JSON da LLM.
- normaliza_cnpj(cnpj: str) -> str: Remove caracteres não numéricos do CNPJ.
- calcular_md5(conteudo_em_bytes: bytes) -> str: Gera o hash MD5 a partir de dados binários.
- is_financial_pdf_name(nome_arquivo: str) -> bool: Verifica heurística de arquivos financeiros pelo nome.
- extract_financial_pages_text_from_bytes(conteudo_em_bytes: bytes, nome_arquivo: str) -> tuple[str, bool]: Extrai texto de páginas financeiras e indica se é PDF escaneado.
- call_ai_with_text(config, cnpj: str, nome_arquivo: str, text: str) -> dict | None: Faz requisição de texto ao Gemini (modo mais econômico).
- file_state_name(file_info) -> str: Retorna o status de processamento do arquivo no Gemini File API.
- call_ai_with_pdf_vision(config, cnpj: str, nome_arquivo: str, conteudo_em_bytes: bytes) -> dict | None: Upload do PDF e chamada Vision (fallback).
- normalizar_resposta_ia(new_data: dict | list | None) -> dict | None: Valida e garante a estrutura adequada da resposta JSON da LLM.
- criar_json_base(cnpj: str) -> dict: Cria cabeçalhos e inicializa a base JSON da empresa.
- processed_hashes(consolidated: dict) -> set[str]: Coleta os hashes MD5 dos PDFs contidos no manifesto de processamento.
- merge_periods(consolidated: dict, new_data: dict) -> int: Mescla novos períodos e contas contábeis no histórico da empresa.
- extrair_dados_quantitativos(cnpj: str, arquivos_em_memoria: list[tuple[str, bytes]], periodos_existentes_db: list[str] | None = None) -> dict: Orquestrador da extração quantitativa incremental em lote.
- carregar_arquivos_em_memoria(pasta_base: Path) -> list[tuple[str, bytes]]: Carrega PDFs recursivos do disco local em buffers bytes.
"""

import argparse
import hashlib
import io
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Callable

import pdfplumber
from dotenv import load_dotenv
from google import genai
from google.genai import types

SCRIPT_DIR = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
DEBUG_FILE = SCRIPT_DIR / "debug_quantitativo.json"

load_dotenv(PROJETO_RAIZ / ".env.local")
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY não encontrada no .env.local.")

CLIENT = genai.Client(api_key=API_KEY)

FINANCIAL_FILENAME_KEYWORDS = [
    "demonstr",
    "dfp",
    "itr",
    "release",
    "resultado",
    "financeira",
    "balanço",
    "balanco",
    "trimestral",
    "anual",
]

NON_FINANCIAL_FILENAME_KEYWORDS = [
    "escritura",
    "ata ",
    "_ata_",
    "rating",
    "garantia",
    "guarantee",
    "contrato",
    "indeniz",
    "aditivo",
    "alienacao",
    "alienação",
    "alienao",
    "cessao",
    "cessão",
    "fiduciaria",
    "fiduciária",
    "fiduciria",
    "creditorio",
    "creditório",
    "creditor",
    "direitos",
    "publicitar",
    "cadastral",
    "referencia",
    "referência",
    "emissao",
    "emissão",
    "refi",
    "corporate",
    "material",
    "formulario",
    "formulário",
    "comunicado",
    "escritur",
]

FINANCIAL_PAGE_KEYWORDS = [
    "ativo total",
    "ativo circulante",
    "passivo total",
    "patrimônio líquido",
    "receita líquida",
    "receita operacional",
    "lucro bruto",
    "ebitda",
    "fluxo de caixa",
    "atividades operacionais",
    "prejuízo do exercício",
    "lucro do exercício",
    "resultado líquido",
    "balanço patrimonial",
    "demonstração do resultado",
    "demonstração dos fluxos",
    "total assets",
    "net revenue",
]

MIN_TEXT_CHARS_PER_PAGE = 100
MAX_TEXT_PAGES_PER_PDF = 30
MAX_VISION_RETRIES = 3


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


def system_instruction_quantitativa(existing_periods: list[str]) -> str:
    return f"""
Você é um analista financeiro sênior especializado em estruturar demonstrações financeiras de empresas brasileiras no padrão da CVM para análise de crédito.

Sua tarefa é ler o PDF ou o texto extraído de demonstrações financeiras e retornar EXCLUSIVAMENTE um JSON válido.

[CONTEXTO]
O JSON atual já contém os seguintes períodos: {existing_periods}
Se o PDF repetir períodos já presentes, priorize apenas períodos novos ou informações faltantes.

[FORMATO OBRIGATÓRIO DE SAÍDA]
Retorne um objeto JSON com esta estrutura:
{{
  "periodos": {{
    "YYYY-MM-DD": {{
      "tipo": "DFP" ou "ITR",
      "demonstracoes": {{
        "BPA": {{
          "1": {{"cd_conta": "1", "ds_conta": "Ativo Total", "valor": 123.45}}
        }},
        "BPP": {{}},
        "DRE": {{}},
        "DFC": {{}},
        "DVA": {{}}
      }}
    }}
  }}
}}

[REGRAS CRÍTICAS]
1. Retorne apenas JSON puro, sem markdown, sem comentários e sem blocos de código.
2. Use datas de referência no formato YYYY-MM-DD.
3. Use somente as chaves de demonstração BPA, BPP, DRE, DFC e DVA.
4. Cada conta deve ser um objeto com exatamente: cd_conta, ds_conta, valor.
5. O campo valor deve ser numérico JSON, nunca string.
6. Preserve os códigos das contas quando o documento os informar.
7. Quando o código da conta não estiver explícito, infira a estrutura mais fiel possível ao padrão CVM e mantenha consistência hierárquica.
8. Não invente períodos inexistentes e não preencha valores ausentes.
9. Se não encontrar dados válidos, retorne {{"periodos": {{}}}}.
10. Não inclua campos fora da estrutura especificada.
"""


def get_generation_config_quantitativo(periodos_existentes: list[str] | None = None):
    existing_periods = periodos_existentes or []
    return types.GenerateContentConfig(
        system_instruction=system_instruction_quantitativa(existing_periods),
        temperature=0.0,
        response_mime_type="application/json",
    )


def normaliza_cnpj(cnpj: str) -> str:
    return "".join(ch for ch in str(cnpj) if ch.isdigit())


def calcular_md5(conteudo_em_bytes: bytes) -> str:
    return hashlib.md5(conteudo_em_bytes).hexdigest()


def is_financial_pdf_name(nome_arquivo: str) -> bool:
    name_lower = nome_arquivo.lower()
    if any(k in name_lower for k in NON_FINANCIAL_FILENAME_KEYWORDS):
        return False
    if any(k in name_lower for k in FINANCIAL_FILENAME_KEYWORDS):
        return True
    return True


def extract_financial_pages_text_from_bytes(conteudo_em_bytes: bytes, nome_arquivo: str) -> tuple[str, bool]:
    financial_text_parts = []
    total_pages = 0
    pages_with_text = 0
    financial_pages_found = 0

    try:
        with pdfplumber.open(io.BytesIO(conteudo_em_bytes)) as pdf:
            total_pages = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                if len(text) > MIN_TEXT_CHARS_PER_PAGE:
                    pages_with_text += 1
                    text_lower = text.lower()
                    if any(kw in text_lower for kw in FINANCIAL_PAGE_KEYWORDS):
                        financial_pages_found += 1
                        financial_text_parts.append(f"\n\n--- PÁGINA {i + 1} ---\n{text}")
                        if financial_pages_found >= MAX_TEXT_PAGES_PER_PDF:
                            break
    except Exception as e:
        print(f"    [pdfplumber] Erro ao abrir {nome_arquivo}: {e}")
        return "", True

    is_scanned = total_pages > 0 and pages_with_text < (total_pages * 0.1)
    extracted_text = "".join(financial_text_parts)
    return extracted_text, is_scanned


def call_ai_with_text(
    config,
    cnpj: str,
    nome_arquivo: str,
    text: str,
    status_callback: Callable[[str], None] | None = None,
) -> dict | None:
    prompt = f"""CNPJ: {cnpj}
Arquivo: {nome_arquivo}

Texto das páginas financeiras extraído do PDF:
{text}

    Extraia os dados financeiros no formato JSON conforme instruído."""

    for attempt in range(3):
        try:
            log_status(f"[IA-texto] Aguardando resposta do Gemini para {nome_arquivo} (Tentativa {attempt + 1}/3)...")
            _emit_status(
                f"Aguardando resposta do Gemini para {nome_arquivo}.",
                status_callback,
            )
            response = CLIENT.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=config,
            )
            return json.loads(response.text)
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "503" in err_msg or "UNAVAILABLE" in err_msg:
                wait_time = (attempt + 1) * 15
                print(f"    [IA-texto] Erro temporário (429/503) em {nome_arquivo}. Aguardando {wait_time}s...")
                time.sleep(wait_time)
                continue
            print(f"    [IA-texto] Erro em {nome_arquivo}: {e}")
            return None
    return None


def file_state_name(file_info) -> str:
    state = getattr(file_info, "state", None)
    if hasattr(state, "name"):
        return state.name
    return str(state or "")


def call_ai_with_pdf_vision(
    config,
    cnpj: str,
    nome_arquivo: str,
    conteudo_em_bytes: bytes,
    status_callback: Callable[[str], None] | None = None,
) -> dict | None:
    for attempt in range(MAX_VISION_RETRIES):
        uploaded = None
        temp_path = None
        try:
            # Extrai apenas a extensão básica (ex: .pdf) para evitar UnicodeEncodeError no tempfile no Windows
            raw_suffix = Path(nome_arquivo).suffix or ".pdf"
            match = re.match(r"^(\.[a-zA-Z0-9]+)", raw_suffix)
            suffix = match.group(1) if match else ".pdf"

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(conteudo_em_bytes)
                temp_path = tmp.name

            log_status(f"    [Vision] Tentativa {attempt + 1}/{MAX_VISION_RETRIES}: preparando upload de {nome_arquivo}...")
            _emit_status(
                f"Preparando upload do PDF {nome_arquivo} para o Gemini.",
                status_callback,
            )
            uploaded = CLIENT.files.upload(file=temp_path)

            log_status(f"    [Vision] Upload concluído para {nome_arquivo}. Aguardando processamento remoto...")
            _emit_status(
                f"Upload concluído. Aguardando o Gemini processar {nome_arquivo}.",
                status_callback,
            )
            while True:
                file_info = CLIENT.files.get(name=uploaded.name)
                if file_state_name(file_info) == "PROCESSING":
                    log_status(f"    [Vision] Gemini ainda está processando {nome_arquivo}...")
                    _emit_status(
                        f"O Gemini ainda está processando {nome_arquivo}.",
                        status_callback,
                    )
                    time.sleep(2)
                    continue
                break

            if file_state_name(file_info) == "FAILED":
                print(f"    [Vision] Falha no processamento do {nome_arquivo}")
                return None

            prompt = (
                f"CNPJ: {cnpj}\n"
                f"Arquivo: {nome_arquivo}\n"
                "Extraia os dados financeiros deste PDF no formato JSON conforme instruído."
            )
            log_status(f"    [Vision] Enviando prompt final ao Gemini para {nome_arquivo}...")
            _emit_status(
                f"Enviando o prompt final ao Gemini para {nome_arquivo}.",
                status_callback,
            )
            response = CLIENT.models.generate_content(
                model="gemini-2.5-flash",
                contents=[prompt, file_info],
                config=config,
            )
            return json.loads(response.text)
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "503" in err_msg or "UNAVAILABLE" in err_msg:
                wait_time = (attempt + 1) * 30
                print(f"    [Vision] Erro temporário (429/503) em {nome_arquivo}. Aguardando {wait_time}s...")
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


def normalizar_resposta_ia(new_data: dict | list | None) -> dict | None:
    if isinstance(new_data, list):
        if new_data and isinstance(new_data[0], dict) and "periodos" in new_data[0]:
            new_data = new_data[0]
        else:
            return None
    if not isinstance(new_data, dict):
        return None
    if "periodos" not in new_data or not isinstance(new_data["periodos"], dict):
        return None
    return new_data


def criar_json_base(cnpj: str) -> dict:
    return {
        "cnpj": normaliza_cnpj(cnpj),
        "periodos": {},
        "processed_files": [],
    }


def processed_hashes(consolidated: dict) -> set[str]:
    hashes = set()
    for item in consolidated.get("processed_files", []):
        if isinstance(item, dict) and item.get("hash_md5"):
            hashes.add(item["hash_md5"])
    return hashes


def merge_periods(consolidated: dict, new_data: dict) -> int:
    novos_periodos = 0
    for periodo, dados in new_data.get("periodos", {}).items():
        if periodo not in consolidated["periodos"]:
            consolidated["periodos"][periodo] = dados
            novos_periodos += 1
            continue

        existing_period = consolidated["periodos"][periodo]
        if not existing_period.get("tipo") and dados.get("tipo"):
            existing_period["tipo"] = dados["tipo"]

        existing_dems = existing_period.setdefault("demonstracoes", {})
        for dem_tipo, contas in dados.get("demonstracoes", {}).items():
            if dem_tipo not in existing_dems:
                existing_dems[dem_tipo] = contas
                continue

            if not isinstance(existing_dems[dem_tipo], dict) or not isinstance(contas, dict):
                continue

            for cd_conta, conta in contas.items():
                if cd_conta not in existing_dems[dem_tipo]:
                    existing_dems[dem_tipo][cd_conta] = conta
    return novos_periodos


def extrair_dados_quantitativos(
    cnpj: str,
    arquivos_em_memoria: list[tuple[str, bytes]],
    periodos_existentes_db: list[str] | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> dict:
    consolidated = criar_json_base(cnpj)
    config = get_generation_config_quantitativo(periodos_existentes_db)
    processed_md5 = processed_hashes(consolidated)
    total_arquivos = len(arquivos_em_memoria)

    log_status(f"[quantitativo] Iniciando processamento de {total_arquivos} arquivo(s) para o CNPJ {cnpj}.")
    if consolidated.get("processed_files"):
        log_status(
            f"[quantitativo] Estado inicial contém {len(consolidated['processed_files'])} "
            f"arquivo(s) já processado(s)."
        )

    for indice, (nome_arquivo, conteudo_em_bytes) in enumerate(arquivos_em_memoria, start=1):
        inicio_arquivo = time.time()
        try:
            hash_md5 = calcular_md5(conteudo_em_bytes)
            if hash_md5 in processed_md5:
                log_status(f"[quantitativo] [{indice}/{total_arquivos}] Pulado por hash já processado: {nome_arquivo}")
                continue

            if not is_financial_pdf_name(nome_arquivo):
                log_status(f"[quantitativo] [{indice}/{total_arquivos}] Pulado por heurística de nome não financeiro: {nome_arquivo}")
                continue

            tamanho_kb = len(conteudo_em_bytes) / 1024
            log_status(
                f"[quantitativo] [{indice}/{total_arquivos}] Analisando {nome_arquivo} "
                f"({tamanho_kb:,.1f} KB | md5={hash_md5[:12]}...)"
            )
            _emit_status(
                f"Analisando o PDF financeiro {nome_arquivo}.",
                status_callback,
            )
            log_status(f"[quantitativo] [{indice}/{total_arquivos}] Extraindo páginas financeiras do PDF em memória...")
            _emit_status(
                f"Extraindo páginas financeiras de {nome_arquivo}.",
                status_callback,
            )
            texto_extraido, is_scanned = extract_financial_pages_text_from_bytes(conteudo_em_bytes, nome_arquivo)

            result = None
            if texto_extraido and not is_scanned:
                char_count = len(texto_extraido)
                estimated_tokens = char_count // 4
                log_status(
                    f"[quantitativo] [{indice}/{total_arquivos}] Texto financeiro extraído com "
                    f"{char_count:,} chars (~{estimated_tokens:,} tokens). Usando modo Texto."
                )
                _emit_status(
                    f"Enviando o texto financeiro de {nome_arquivo} ao Gemini.",
                    status_callback,
                )
                result = call_ai_with_text(
                    config,
                    cnpj,
                    nome_arquivo,
                    texto_extraido,
                    status_callback=status_callback,
                )
            else:
                log_status(
                    f"[quantitativo] [{indice}/{total_arquivos}] PDF sem texto financeiro útil suficiente. "
                    f"Usando modo Vision."
                )
                _emit_status(
                    f"Sem texto financeiro útil em {nome_arquivo}. Usando modo Vision.",
                    status_callback,
                )
                result = call_ai_with_pdf_vision(
                    config,
                    cnpj,
                    nome_arquivo,
                    conteudo_em_bytes,
                    status_callback=status_callback,
                )

            result = normalizar_resposta_ia(result)
            if result is None:
                duracao = time.time() - inicio_arquivo
                log_status(f"[quantitativo] [{indice}/{total_arquivos}] Falha: nenhum JSON válido extraído de {nome_arquivo} após {duracao:.1f}s.")
                continue

            n_periodos = merge_periods(consolidated, result)
            consolidated["processed_files"].append(
                {
                    "nome_arquivo": nome_arquivo,
                    "hash_md5": hash_md5,
                }
            )
            processed_md5.add(hash_md5)
            duracao = time.time() - inicio_arquivo
            total_periodos = len(consolidated.get("periodos", {}))
            log_status(
                f"[quantitativo] [{indice}/{total_arquivos}] Sucesso: "
                f"{n_periodos if n_periodos else len(result.get('periodos', {}))} período(s) aproveitado(s) "
                f"em {duracao:.1f}s. Total consolidado: {total_periodos} período(s)."
            )
            _emit_status(
                f"Extração concluída para {nome_arquivo}. {total_periodos} período(s) consolidados até agora.",
                status_callback,
            )
            time.sleep(1)
        except Exception as e:
            duracao = time.time() - inicio_arquivo
            log_status(f"[quantitativo] [{indice}/{total_arquivos}] Erro ao processar {nome_arquivo} após {duracao:.1f}s: {e}")
            continue

    log_status(
        f"[quantitativo] Processamento concluído. Total consolidado final: "
        f"{len(consolidated.get('periodos', {}))} período(s)."
    )
    return consolidated


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
    parser = argparse.ArgumentParser(description="Módulo de IA Quantitativa - PDFs em memória")
    parser.add_argument("pasta_base", help="Pasta com PDFs de teste")
    parser.add_argument("--cnpj", default="00000000000000", help="CNPJ para o teste local")
    args = parser.parse_args()

    pasta_base = Path(args.pasta_base)
    if not pasta_base.exists():
        raise SystemExit(f"Pasta não encontrada: {pasta_base}")

    inicio_total = time.time()
    log_status("=" * 72)
    log_status("TESTE LOCAL - SERVIÇO DE IA QUANTITATIVA")
    log_status(f"Pasta base: {pasta_base}")
    log_status(f"CNPJ informado: {args.cnpj}")
    log_status("Fluxo: disco local -> bytes em memória -> função principal -> JSON final")
    log_status("=" * 72)

    arquivos_em_memoria = carregar_arquivos_em_memoria(pasta_base)
    if not arquivos_em_memoria:
        raise SystemExit("Nenhum PDF encontrado para teste.")

    total_bytes = sum(len(conteudo) for _, conteudo in arquivos_em_memoria)
    log_status(
        f"[debug] Iniciando chamada principal com {len(arquivos_em_memoria)} arquivo(s) "
        f"e {total_bytes / (1024 * 1024):.2f} MB em memória."
    )
    resultado = extrair_dados_quantitativos(args.cnpj, arquivos_em_memoria)
    with open(DEBUG_FILE, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    duracao_total = time.time() - inicio_total
    log_status(f"[debug] Resultado salvo em: {DEBUG_FILE}")
    log_status(f"[debug] Períodos consolidados no resultado: {len(resultado.get('periodos', {}))}")
    log_status(f"[debug] Tempo total da execução: {duracao_total:.1f}s")
