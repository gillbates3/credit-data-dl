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
SYSTEM_INSTRUCTION = """
Você é um analista financeiro sênior especializado em estruturar balanços de empresas brasileiras no padrão da CVM para análise de crédito de debêntures.

Sua tarefa: ler o texto das demonstrações financeiras fornecido e extrair os dados em JSON.

REGRAS CRÍTICAS:
1. SEMPRE use a coluna "Consolidado" quando houver "Controladora" e "Consolidado".
2. NUNCA recalcule valores. Copie EXATAMENTE o valor que aparece na linha totalizadora do PDF.
3. Normalize UNIDADES: se o PDF diz "(Em milhares de reais)", multiplique todos os valores por 1.000.
   Exemplo: se a tabela mostra "24.102", o valor JSON deve ser 24102000.0
4. DFC - MAPEAMENTO CVM:
   - 6.01: "Caixa líquido (aplicado nas) proveniente das atividades operacionais". É o TOTAL FINAL da seção operacional.
   - 6.02: "Caixa líquido (aplicado nas) proveniente das atividades de investimento".
   - 6.03: "Caixa líquido (aplicado nas) proveniente das atividades de financiamento".
5. ATENÇÃO COLUNAS: Certifique-se de extrair o valor da coluna correspondente ao período mais recente (geralmente a primeira coluna de valores após a descrição). Ignore saldos comparativos de anos anteriores que aparecem na mesma tabela.
6. Período: use a data de encerramento no formato "YYYY-MM-DD" e "tipo" (DFP para anual, ITR para trimestral).

ESTRUTURA JSON OBRIGATÓRIA (responda apenas o JSON, sem explicações):
{
  "periodos": {
    "2024-12-31": {
      "tipo": "DFP",
      "demonstracoes": {
        "BPA": {
          "1":    { "cd_conta": "1",    "ds_conta": "Ativo Total",       "valor": 1000000.0, "ordem": 1 },
          "1.01": { "cd_conta": "1.01", "ds_conta": "Ativo Circulante",  "valor": 500000.0,  "ordem": 2 }
        },
        "BPP": {
          "2":    { "cd_conta": "2",    "ds_conta": "Passivo Total",     "valor": 1000000.0, "ordem": 1 }
        },
        "DRE": {
          "3.01": { "cd_conta": "3.01", "ds_conta": "Receita Líquida",  "valor": 800000.0,  "ordem": 1 }
        },
        "DFC": {
          "6.01": { "cd_conta": "6.01", "ds_conta": "Caixa Atividades Operacionais", "valor": 120000.0, "ordem": 1 },
          "6.02": { "cd_conta": "6.02", "ds_conta": "Caixa Atividades Investimento", "valor": -50000.0, "ordem": 2 },
          "6.03": { "cd_conta": "6.03", "ds_conta": "Caixa Atividades Financiamento","valor": -30000.0, "ordem": 3 }
        }
      }
    }
  }
}
"""

# ─── Modelo Gemini ────────────────────────────────────────────────────────────
def get_model():
    return genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_INSTRUCTION,
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


def merge_periods(consolidated: dict, new_data: dict):
    """Mescla novos períodos no dicionário consolidado (não sobrescreve dados já existentes)."""
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

def extract_from_pdfs(cnpj: str, pdf_paths: list[Path]) -> dict | None:
    """
    Pipeline híbrido:
    1. Filtra PDFs não financeiros (por nome)
    2. Extrai texto com pdfplumber (grátis)
    3. Se tem texto → envia texto para IA (barato)
    4. Se escaneado  → envia PDF para IA Vision (caro, fallback)
    """
    consolidated = {"periodos": {}}
    model = get_model()
    token_report = {"text_mode": 0, "vision_mode": 0, "skipped": 0}

    for path in pdf_paths:
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

        if result:
            merge_periods(consolidated, result)
            n_periodos = len(result.get("periodos", {}))
            print(f"    ✅ {n_periodos} período(s) extraído(s).")
        else:
            print(f"    ❌ Nenhum dado extraído de {path.name}.")

        time.sleep(1)  # rate limit protection

    print(f"\n  📊 Resumo [{cnpj}]:")
    print(f"     Modo Texto (barato): {token_report['text_mode']} arquivo(s)")
    print(f"     Modo Vision (caro):  {token_report['vision_mode']} arquivo(s)")
    print(f"     Pulados:             {token_report['skipped']} arquivo(s)")

    return consolidated if consolidated["periodos"] else None


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

        json_saida = cnpj_dir / "dados_financeiros.json"

        if json_saida.exists():
            print(f"  ⏭  dados_financeiros.json já existe. Pulando.")
            print(f"     (Apague o arquivo para re-gerar.)")
            continue

        pdf_paths = sorted(cnpj_dir.glob("*.pdf"))

        if not pdf_paths:
            print(f"  ❌ Nenhum PDF encontrado.")
            continue

        print(f"  {len(pdf_paths)} PDFs encontrados na pasta.")

        dados = extract_from_pdfs(cnpj, pdf_paths)

        if dados:
            with open(json_saida, "w", encoding="utf-8") as f:
                json.dump(dados, f, indent=2, ensure_ascii=False)
            n = len(dados["periodos"])
            print(f"\n  ✅ Sucesso: {json_saida.name} gerado com {n} período(s)!")
        else:
            print(f"\n  ❌ Falha: nenhum dado financeiro encontrado nos PDFs.")


if __name__ == "__main__":
    main()
