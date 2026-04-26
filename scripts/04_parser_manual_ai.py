"""
05b_ai_pdf_parser.py

Parser híbrido e econômico para extração de dados financeiros de PDFs.

ESTRATÉGIA DE ECONOMIA DE TOKENS:
  1. Filtra PDFs por nome de arquivo (pula escrituras, ratings, atas, etc.)
  2. Usa pdfplumber para extrair TEXTO das páginas relevantes (GRÁTIS)
  3. Manda apenas o TEXTO das tabelas para a IA (5-10x mais barato que mandar PDF)
  4. Fallback para PDF Vision apenas em PDFs escaneados (sem texto extraível)

Compatível com o 04_parser_silver.py (mesmo formato de saída JSON).
"""
import os
import io
import json
import time
from pathlib import Path

import pdfplumber
import google.generativeai as genai
from dotenv import load_dotenv

# ─── Configurações ────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
MANUAL_UPLOADS = PROJETO_RAIZ / "data" / "01_landing" / "manual_uploads"

load_dotenv(PROJETO_RAIZ / ".env.local")
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    print("ERRO: GEMINI_API_KEY não encontrada no .env.local.")
    exit(1)

genai.configure(api_key=API_KEY)

# ─── Filtros de arquivo ───────────────────────────────────────────────────────
# PDFs cujo NOME indica que são demonstrações financeiras
FINANCIAL_FILENAME_KEYWORDS = [
    "demonstr", "dfp", "itr", "release", "resultado",
    "financeira", "balanço", "balanco", "trimestral", "anual",
]

# PDFs cujo NOME indica que são documentos NÃO financeiros (pular)
NON_FINANCIAL_FILENAME_KEYWORDS = [
    "escritura", "ata ", "_ata_", "rating", "garantia", "guarantee",
    "contrato", "indeniz", "aditivo", "alienacao", "alienação", "alienao",
    "cessao", "cessão", "fiduciaria", "fiduciária", "fiduciria",
    "creditorio", "creditório", "creditor", "direitos",
    "publicitar", "cadastral", "referencia", "referência",
    "emissao", "emissão", "refi", "corporate", "material",
    "formulario", "formulário", "comunicado", "escritur",
]

# Palavras-chave que identificam páginas com tabelas financeiras dentro de um PDF
FINANCIAL_PAGE_KEYWORDS = [
    "ativo total", "ativo circulante", "passivo total", "patrimônio líquido",
    "receita líquida", "receita operacional", "lucro bruto", "ebitda",
    "fluxo de caixa", "atividades operacionais", "prejuízo do exercício",
    "lucro do exercício", "resultado líquido", "balanço patrimonial",
    "demonstração do resultado", "demonstração dos fluxos",
    "total assets", "net revenue",  # para PDFs em inglês
]

# Mínimo de caracteres de texto em uma página para considerá-la "legível"
MIN_TEXT_CHARS_PER_PAGE = 100

# Máximo de páginas com texto para enviar à IA (controle de custo)
MAX_TEXT_PAGES_PER_PDF = 30

# ─── System Prompt ────────────────────────────────────────────────────────────
def SYSTEM_INSTRUCTION_GEN(existing_json_str: str) -> str:
    return f"""
Você é um analista financeiro sênior especializado em estruturar balanços de empresas brasileiras no padrão da CVM para análise de crédito de debêntures.

Sua tarefa: ler o texto das demonstrações financeiras fornecido e extrair os dados em JSON.

[CONTEXTO]
O arquivo JSON atual da empresa já contém os seguintes períodos: {existing_json_str}
Se o PDF que você está lendo contiver esses mesmos períodos, foque em extrair apenas períodos NOVOS ou informações que faltam. Se os dados forem idênticos, você pode omiti-los do retorno para economizar tokens.

REGRAS CRÍTICAS:
...
"""

# ─── Modelo Gemini ────────────────────────────────────────────────────────────
def get_model(existing_json: dict):
    existing_periods = list(existing_json.get("periodos", {}).keys())
    return genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_INSTRUCTION_GEN(str(existing_periods)),
        generation_config=genai.GenerationConfig(
            temperature=0.0,
            response_mime_type="application/json",
        )
    )

# ─── Funções auxiliares ───────────────────────────────────────────────────────

def is_financial_pdf(path: Path) -> bool:
    """Decide se um PDF deve ser processado com base no nome do arquivo."""
    name_lower = path.name.lower()
    # Pular PDFs claramente não financeiros
    if any(k in name_lower for k in NON_FINANCIAL_FILENAME_KEYWORDS):
        return False
    # Priorizar PDFs claramente financeiros
    if any(k in name_lower for k in FINANCIAL_FILENAME_KEYWORDS):
        return True
    # PDFs com nome ambíguo: processar (melhor falso positivo que falso negativo)
    return True


def extract_financial_pages_text(path: Path) -> tuple[str, bool]:
    """
    Extrai texto das páginas financeiras de um PDF usando pdfplumber.
    
    Retorna:
        (texto_extraido, is_scanned)
        - texto_extraido: texto das páginas financeiras concatenado
        - is_scanned: True se o PDF parece ser uma imagem escaneada (sem texto)
    """
    financial_text_parts = []
    total_pages = 0
    pages_with_text = 0
    financial_pages_found = 0

    try:
        with pdfplumber.open(str(path)) as pdf:
            total_pages = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                if len(text) > MIN_TEXT_CHARS_PER_PAGE:
                    pages_with_text += 1
                    text_lower = text.lower()
                    if any(kw in text_lower for kw in FINANCIAL_PAGE_KEYWORDS):
                        financial_pages_found += 1
                        financial_text_parts.append(
                            f"\n\n--- PÁGINA {i+1} ---\n{text}"
                        )
                        if financial_pages_found >= MAX_TEXT_PAGES_PER_PDF:
                            break
    except Exception as e:
        print(f"    [pdfplumber] Erro ao abrir {path.name}: {e}")
        return "", True  # Tratar como escaneado se não abrir

    is_scanned = pages_with_text < (total_pages * 0.1)  # < 10% das páginas têm texto
    extracted_text = "".join(financial_text_parts)

    return extracted_text, is_scanned


def call_ai_with_text(model, cnpj: str, filename: str, text: str) -> dict | None:
    """Chama o Gemini enviando TEXTO extraído (barato)."""
    prompt = f"""Arquivo: {filename}

Texto das páginas financeiras extraído do PDF:
{text}

Extraia os dados financeiros no formato JSON conforme instruído."""
    
    try:
        response = model.generate_content(prompt)
        return json.loads(response.text)
    except Exception as e:
        print(f"    [IA-texto] Erro em {filename}: {e}")
        return None


def call_ai_with_pdf_vision(model, cnpj: str, path: Path) -> dict | None:
    """
    Fallback: envia PDF completo ao Gemini Vision (para PDFs escaneados).
    Mais caro em tokens, usado apenas quando pdfplumber não consegue extrair texto.
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"    [Vision] Fazendo upload de {path.name}...")
            uploaded = genai.upload_file(str(path), mime_type="application/pdf")
            
            while True:
                file_info = genai.get_file(uploaded.name)
                if file_info.state.name == "PROCESSING":
                    time.sleep(2)
                else:
                    break
            
            if file_info.state.name == "FAILED":
                print(f"    [Vision] Falha no processamento do {path.name}")
                return None

            prompt = f"Arquivo: {path.name}\nExtraia os dados financeiros deste PDF no formato JSON conforme instruído."
            response = model.generate_content([prompt, file_info])
            genai.delete_file(uploaded.name)
            return json.loads(response.text)

        except Exception as e:
            if "429" in str(e):
                wait_time = (attempt + 1) * 30
                print(f"    [Vision] Quota (429). Aguardando {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"    [Vision] Erro em {path.name}: {e}")
                return None
    return None


def merge_periods(consolidated: dict, new_data: dict | list):
    """Mescla novos períodos no dicionário consolidado (não sobrescreve dados já existentes)."""
    if isinstance(new_data, list):
        if len(new_data) > 0 and isinstance(new_data[0], dict) and "periodos" in new_data[0]:
            new_data = new_data[0]
        else:
            print("    ⚠️ Resposta da IA em formato de lista inválida. Pulando mesclagem.")
            return

    if not isinstance(new_data, dict):
        print(f"    ⚠️ Resposta da IA em formato inválido ({type(new_data)}). Pulando mesclagem.")
        return

    for periodo, dados in new_data.get("periodos", {}).items():
        if periodo not in consolidated["periodos"]:
            consolidated["periodos"][periodo] = dados
        else:
            existing_dems = consolidated["periodos"][periodo].get("demonstracoes", {})
            for dem_tipo, contas in dados.get("demonstracoes", {}).items():
                if dem_tipo not in existing_dems:
                    existing_dems[dem_tipo] = contas
            consolidated["periodos"][periodo]["demonstracoes"] = existing_dems


# ─── Função principal de extração ─────────────────────────────────────────────

def extract_from_pdfs(cnpj: str, pdf_paths: list[Path], consolidated: dict) -> dict | None:
    """Pipeline híbrido incremental."""
    model = get_model(consolidated)
    token_report = {"text_mode": 0, "vision_mode": 0, "skipped": 0}
    
    # Manifest de arquivos já processados
    if "processed_files" not in consolidated:
        consolidated["processed_files"] = []
    
    processed_set = {f["name"] for f in consolidated["processed_files"]}

    for path in pdf_paths:
        if path.name in processed_set:
            print(f"  ⏭  Pulado (já processado): {path.name}")
            continue

        # ── Etapa 1: Filtrar por nome ─────────────────────────────────────────
        if not is_financial_pdf(path):
            print(f"  ⏭  Pulado (não financeiro): {path.name}")
            token_report["skipped"] += 1
            continue

        print(f"  📄 Analisando: {path.name}")

        # ── Etapa 2: Extrair texto com pdfplumber ────────────────────────────
        text, is_scanned = extract_financial_pages_text(path)

        result = None

        if text and not is_scanned:
            # ── Etapa 3: Modo Texto (barato) ──────────────────────────────────
            char_count = len(text)
            estimated_tokens = char_count // 4
            print(f"    [Texto] {char_count:,} chars (~{estimated_tokens:,} tokens). Enviando à IA...")
            result = call_ai_with_text(model, cnpj, path.name, text)
            if result:
                token_report["text_mode"] += 1
            else:
                # Se IA falhou com texto, tenta Vision como fallback
                print(f"    [Texto→Vision] IA falhou. Tentando Vision...")
                result = call_ai_with_pdf_vision(model, cnpj, path)
                if result:
                    token_report["vision_mode"] += 1

        else:
            # ── Etapa 4: Modo Vision (fallback para escaneados) ───────────────
            print(f"    [Vision] PDF escaneado/sem texto. Enviando PDF à IA...")
            result = call_ai_with_pdf_vision(model, cnpj, path)
            if result:
                token_report["vision_mode"] += 1

        if isinstance(result, list):
            if len(result) > 0 and isinstance(result[0], dict) and "periodos" in result[0]:
                result = result[0]
            else:
                result = None

        if result and isinstance(result, dict):
            merge_periods(consolidated, result)
            consolidated["processed_files"].append({
                "name": path.name,
                "timestamp": path.stat().st_mtime
            })
            n_periodos = len(result.get("periodos", {}))
            print(f"    ✅ {n_periodos} período(s) extraído(s).")
        else:
            print(f"    ❌ Nenhum dado extraído de {path.name} (Formato inválido ou nulo).")

        time.sleep(1)  # rate limit protection

    return consolidated


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not MANUAL_UPLOADS.exists():
        print(f"A pasta {MANUAL_UPLOADS} não existe.")
        return

    for cnpj_dir in sorted(MANUAL_UPLOADS.iterdir()):
        if not cnpj_dir.is_dir():
            continue

        cnpj = cnpj_dir.name
        print(f"\n{'='*55}\nProcessando CNPJ: {cnpj}\n{'='*55}")

        json_saida = cnpj_dir / f"{cnpj}.json"
        
        # Carrega existente se houver
        consolidated = {"periodos": {}, "processed_files": []}
        if json_saida.exists():
            try:
                with open(json_saida, encoding="utf-8") as f:
                    consolidated = json.load(f)
            except:
                pass

        pdf_paths = sorted(cnpj_dir.glob("*.pdf"))
        if not pdf_paths:
            print(f"  ❌ Nenhum PDF encontrado.")
            continue

        dados = extract_from_pdfs(cnpj, pdf_paths, consolidated)

        if dados and dados.get("periodos"):
            with open(json_saida, "w", encoding="utf-8") as f:
                json.dump(dados, f, indent=2, ensure_ascii=False)
            n = len(dados["periodos"])
            print(f"\n  ✅ {json_saida.name} atualizado com {n} período(s)!")
        else:
            print(f"\n  ⏭  Sem novos dados para processar.")


if __name__ == "__main__":
    main()
