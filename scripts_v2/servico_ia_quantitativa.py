"""
Script: servico_ia_quantitativa.py
Descrição: Serviço quantitativo baseado em LLM (Gemini) para ESTRUTURAÇÃO de
           demonstrações financeiras em JSON (padrão CVM), a partir do **Markdown**
           já convertido do documento (fonte única compartilhada com a trilha
           qualitativa).

           DECISÃO DE ARQUITETURA (2026-09-21):
           - A conversão documento→Markdown é feita UMA vez: PDF via Jina OCR,
             não-PDF via Docling (ver `servico_ia_qualitativa.extrair_markdown_documento`).
           - A trilha quantitativa NÃO lê mais o PDF diretamente (removidos
             pdfplumber e o modo Gemini Vision). Ela recebe o Markdown e usa o
             Gemini apenas para MAPEAR o conteúdo → JSON CVM (cd_conta, ds_conta,
             valor; BPA/BPP/DRE/DFC/DVA; períodos).
           - O gate deixou de ser por NOME de arquivo e passou a ser por CONTEÚDO
             do Markdown (`markdown_tem_sinais_financeiros`). O próprio Gemini é o
             árbitro final (retorna {"periodos": {}} quando não há dados).

Funções/Procedimentos:
- log_status / _emit_status: logging e status humano ao orquestrador.
- system_instruction_quantitativa / get_generation_config_quantitativo: prompt e config JSON estruturada.
- normaliza_cnpj / calcular_md5: utilidades.
- normalizar_resposta_ia / criar_json_base / merge_periods: validação e consolidação do JSON.
- markdown_tem_sinais_financeiros(markdown) -> bool: gate por conteúdo.
- call_ai_with_markdown(config, cnpj, nome, markdown, status_callback) -> dict | None: chama o Gemini sobre o Markdown.
- extrair_quant_de_markdown(cnpj, nome, markdown, periodos_existentes_db, status_callback) -> dict | None: trilha quant a partir do Markdown.
"""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Callable

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

# Palavras-chave de demonstração financeira usadas como GATE POR CONTEÚDO do Markdown.
FINANCIAL_PAGE_KEYWORDS = [
    "ativo total",
    "ativo circulante",
    "passivo total",
    "passivo circulante",
    "patrimônio líquido",
    "patrimonio liquido",
    "receita líquida",
    "receita liquida",
    "receita operacional",
    "lucro bruto",
    "ebitda",
    "fluxo de caixa",
    "atividades operacionais",
    "prejuízo do exercício",
    "prejuizo do exercicio",
    "lucro do exercício",
    "lucro do exercicio",
    "resultado líquido",
    "resultado liquido",
    "balanço patrimonial",
    "balanco patrimonial",
    "demonstração do resultado",
    "demonstracao do resultado",
    "demonstração dos fluxos",
    "demonstracao dos fluxos",
    "total assets",
    "net revenue",
]

MIN_SINAIS_FINANCEIROS = 2  # nº mínimo de palavras-chave distintas p/ acionar a trilha quant


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

Sua tarefa é ler o Markdown (transcrição fiel do documento) e retornar EXCLUSIVAMENTE um JSON válido.

[CONTEXTO]
O JSON atual já contém os seguintes períodos: {existing_periods}
Se o documento repetir períodos já presentes, priorize apenas períodos novos ou informações faltantes.

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


def markdown_tem_sinais_financeiros(markdown: str) -> bool:
    """Gate por CONTEÚDO (não por nome de arquivo): decide se vale acionar o Gemini
    para extração quantitativa a partir do Markdown já gerado (Jina/Docling).

    Procura palavras-chave típicas de demonstrações financeiras. É apenas um
    guarda-custo local; o próprio Gemini é o árbitro final (retorna
    {"periodos": {}} quando não há dados).
    """
    if not markdown:
        return False
    texto = markdown.lower()
    encontrados = {kw for kw in FINANCIAL_PAGE_KEYWORDS if kw in texto}
    return len(encontrados) >= MIN_SINAIS_FINANCEIROS


def call_ai_with_markdown(
    config,
    cnpj: str,
    nome_arquivo: str,
    markdown: str,
    status_callback: Callable[[str], None] | None = None,
) -> dict | None:
    """Estrutura o Markdown (gerado por Jina/Docling) em JSON CVM via Gemini."""
    prompt = f"""CNPJ: {cnpj}
Arquivo: {nome_arquivo}

Conteúdo do documento em Markdown (transcrição fiel por OCR/conversão; tabelas podem estar em HTML ou em Markdown):
{markdown}

Extraia os dados financeiros no formato JSON conforme instruído."""

    for attempt in range(3):
        try:
            log_status(f"[IA-markdown] Aguardando resposta do Gemini para {nome_arquivo} (Tentativa {attempt + 1}/3)...")
            _emit_status(
                f"Estruturando os dados financeiros de {nome_arquivo} (Gemini).",
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
                print(f"    [IA-markdown] Erro temporário (429/503) em {nome_arquivo}. Aguardando {wait_time}s...")
                time.sleep(wait_time)
                continue
            print(f"    [IA-markdown] Erro em {nome_arquivo}: {e}")
            return None
    return None


def extrair_quant_de_markdown(
    cnpj: str,
    nome_arquivo: str,
    markdown: str,
    periodos_existentes_db: list[str] | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> dict | None:
    """Trilha quantitativa a partir do Markdown já convertido (fonte única com a quali).

    Retorna dict {"periodos": {...}} (normalizado) ou None quando não há sinais
    financeiros no conteúdo ou o Gemini não devolve dados válidos.
    """
    if not markdown_tem_sinais_financeiros(markdown):
        log_status(f"[quantitativo] {nome_arquivo}: sem sinais financeiros no Markdown; trilha quant pulada.")
        return None
    config = get_generation_config_quantitativo(periodos_existentes_db)
    resultado = call_ai_with_markdown(config, cnpj, nome_arquivo, markdown, status_callback=status_callback)
    return normalizar_resposta_ia(resultado)


if __name__ == "__main__":
    # Teste local: converte cada documento -> Markdown (Jina/Docling) e roda a quant.
    try:
        from scripts_v2.servico_ia_qualitativa import (
            carregar_arquivos_em_memoria,
            extrair_markdown_documento,
        )
    except ImportError:
        from servico_ia_qualitativa import (
            carregar_arquivos_em_memoria,
            extrair_markdown_documento,
        )

    parser = argparse.ArgumentParser(description="Módulo de IA Quantitativa - a partir do Markdown")
    parser.add_argument("pasta_base", help="Pasta com documentos de teste")
    parser.add_argument("--cnpj", default="00000000000000", help="CNPJ para o teste local")
    args = parser.parse_args()

    pasta_base = Path(args.pasta_base)
    if not pasta_base.exists():
        raise SystemExit(f"Pasta não encontrada: {pasta_base}")

    inicio_total = time.time()
    log_status("=" * 72)
    log_status("TESTE LOCAL - SERVIÇO DE IA QUANTITATIVA (Markdown -> JSON CVM)")
    log_status(f"Pasta base: {pasta_base}")
    log_status(f"CNPJ informado: {args.cnpj}")
    log_status("Fluxo: documento -> Markdown (Jina/Docling) -> gate por conteúdo -> Gemini -> JSON")
    log_status("=" * 72)

    arquivos_em_memoria = carregar_arquivos_em_memoria(pasta_base)
    if not arquivos_em_memoria:
        raise SystemExit("Nenhum documento suportado encontrado para teste.")

    consolidado = criar_json_base(args.cnpj)
    for nome, conteudo in arquivos_em_memoria:
        markdown, modo = extrair_markdown_documento(args.cnpj, nome, conteudo)
        if modo == "placeholder":
            continue
        resultado = extrair_quant_de_markdown(args.cnpj, nome, markdown, [])
        if resultado and resultado.get("periodos"):
            merge_periods(consolidado, resultado)
            consolidado["processed_files"].append({"nome_arquivo": nome, "hash_md5": calcular_md5(conteudo)})

    with open(DEBUG_FILE, "w", encoding="utf-8") as f:
        json.dump(consolidado, f, ensure_ascii=False, indent=2)
    duracao_total = time.time() - inicio_total
    log_status(f"[debug] Resultado salvo em: {DEBUG_FILE}")
    log_status(f"[debug] Períodos consolidados no resultado: {len(consolidado.get('periodos', {}))}")
    log_status(f"[debug] Tempo total da execução: {duracao_total:.1f}s")
