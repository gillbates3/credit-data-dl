"""
Script: 05_consolidacao_silver.py
Descrição: Consolida os dados financeiros da camada Landing (CVM filtrados) e dados manuais na camada Silver.
           Gera um arquivo JSON consolidado por empresa contendo contas de nível intermediário (1 e 2).
           Mescla informações da CVM com dados estruturados obtidos por uploads manuais (ex: via IA).

Funções/Procedimentos:
- carregar_empresas() -> list[dict]: Lê a base de empresas cadastradas no `empresas.csv`.
- nivel_conta(cd_conta: str) -> int: Retorna o nível de profundidade na hierarquia da conta contábil (ex: 3.01 = nível 2).
- normaliza_cnpj(cnpj: str) -> str: Filtra e remove caracteres não numéricos do CNPJ.
- normaliza_cod(cod: str) -> str: Normaliza o código CVM, tratando zeros à esquerda em códigos numéricos.
- parse_valor(valor_str: str) -> float | None: Converte uma string no formato de moeda CVM para tipo float numérico.
- carregar_manual_dados(cnpj: str) -> dict | None: Carrega o JSON de dados financeiros extraído de PDFs manuais (se houver).
- descobrir_csvs_filtrados() -> dict[str, list[Path]]: Varre a landing zone de DFP e ITR retornando um dicionário com os CSVs de cada demonstração.
- ler_csv_cvm(csv_path: Path) -> list[dict]: Efetua a leitura de um arquivo CSV filtrado de dados da CVM.
- processar_linhas(linhas: list[dict], cod_cvm_alvo: str) -> dict[str, dict[str, dict]]: Filtra, limpa e organiza as contas da CVM por período de referência para uma empresa.
- construir_json_empresa(empresa: dict, csvs_por_chave: dict[str, list[Path]]) -> dict: Constrói a estrutura consolidada da empresa integrando todas as demonstrações financeiras (BPA, BPP, DRE, DFC, etc.) da CVM.
- main(): Orquestra a execução, aplicando lógica de verificação incremental (mtime) e salvando as estruturas consolidadas na camada Silver.
"""

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

# ── Configuração ─────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
LANDING      = PROJETO_RAIZ / "data" / "01_landing" / "cvm_raw"
SILVER       = PROJETO_RAIZ / "data" / "02_silver"
EMPRESAS_CSV   = PROJETO_RAIZ / "empresas.csv"
MANUAL_UPLOADS = PROJETO_RAIZ / "data" / "01_landing" / "manual_uploads"

# Nível máximo de conta a incluir (2 = "3.01", exclui "3.01.01" e mais fundo)
NIVEL_MAX = 2

# Mapeamento de tabela CVM → chave no JSON
TABELA_PARA_CHAVE = {
    "BPA": "BPA",   # Balanço Ativo
    "BPP": "BPP",   # Balanço Passivo + PL
    "DRE": "DRE",   # Resultado
    "DFC_MD": "DFC", # Fluxo de Caixa (Método Direto — preferido)
    "DFC_MI": "DFC", # Fluxo de Caixa (Método Indireto — fallback)
    "DVA": "DVA",   # Valor Adicionado
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def carregar_empresas() -> list[dict]:
    with open(EMPRESAS_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def nivel_conta(cd_conta: str) -> int:
    """Retorna o nível hierárquico de uma conta CVM.
    '1'      → nível 1
    '1.01'   → nível 2
    '1.01.01'→ nível 3
    """
    return len(cd_conta.strip().split("."))


def normaliza_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj)


def normaliza_cod(cod: str) -> str:
    s = cod.strip()
    return str(int(s)) if s.isdigit() else s


def parse_valor(valor_str: str) -> float | None:
    if valor_str is None: return None
    v = str(valor_str).strip().replace(".", "").replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None

def carregar_manual_dados(cnpj: str) -> dict | None:
    """Busca dados na pasta de uploads manuais.
    Decodifica arquivos JSON ou CSV que seguem o formato esperado.
    """
    pasta = MANUAL_UPLOADS / cnpj
    if not pasta.exists():
        return None
    
    # Exemplo: busca por um balanco.json ou balanco.csv
    # Aqui implementamos uma logica 'coringa' conforme requisitado
    json_path = pasta / "dados_financeiros.json"
    if json_path.exists():
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)
            
    # Fallback para outros arquivos pode ser adicionado aqui
    return None


def descobrir_csvs_filtrados() -> dict[str, list[Path]]:
    """
    Mapeia tipo_tabela → lista de arquivos CSV filtrados encontrados.
    Ex: { "dfp/BPA": [Path(.../dfp/2022/filtrado/BPA_con.csv), ...] }
    """
    resultado: dict[str, list[Path]] = defaultdict(list)
    for tipo in ("dfp", "itr"):
        filtrado_dirs = sorted((LANDING / tipo).rglob("filtrado"))
        for d in filtrado_dirs:
            for csv_path in sorted(d.glob("*.csv")):
                # Ex: BPA_con.csv → tabela = BPA
                stem = csv_path.stem  # "BPA_con"
                tabela = stem.replace("_con", "").replace("_ind", "").upper()
                chave = f"{tipo}/{tabela}"
                resultado[chave].append(csv_path)
    return resultado


# ── Parser principal ──────────────────────────────────────────────────────────

def ler_csv_cvm(csv_path: Path) -> list[dict]:
    """Lê um CSV filtrado da CVM e retorna lista de dicts."""
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def processar_linhas(
    linhas: list[dict],
    cod_cvm_alvo: str,
) -> dict[str, dict[str, dict]]:
    """
    Processa linhas de um CSV CVM para uma empresa.
    Retorna: { "2024-12-31": { "3.01": {cd_conta, ds_conta, valor, ordem}, ... } }
    """
    cod_alvo_norm = normaliza_cod(cod_cvm_alvo)
    por_periodo: dict[str, dict] = defaultdict(dict)

    for linha in linhas:
        if normaliza_cod(linha.get("CD_CVM", "")) != cod_alvo_norm:
            continue

        cd_conta = linha.get("CD_CONTA", "").strip()
        if not cd_conta:
            continue

        # Filtra pelo nível intermediário
        if nivel_conta(cd_conta) > NIVEL_MAX:
            continue

        dt_refer = linha.get("DT_REFER", "").strip()   # "2024-12-31"
        ds_conta = linha.get("DS_CONTA", "").strip()
        vl_conta_str = linha.get("VL_CONTA", "").strip()
        ordem_str = linha.get("ORDEM_EXERC", "").strip()

        valor = parse_valor(vl_conta_str)
        if valor is None:
            continue

        # ORDEM_EXERC: "ÚLTIMO" = período atual, "PENÚLTIMO" = comparativo
        # Inclui só o período atual para evitar duplicatas
        if ordem_str and "LTIMO" in ordem_str.upper() and "PEN" in ordem_str.upper():
            continue  # pula comparativo

        por_periodo[dt_refer][cd_conta] = {
            "cd_conta": cd_conta,
            "ds_conta": ds_conta,
            "valor": valor,
        }

    return por_periodo


def construir_json_empresa(
    empresa: dict,
    csvs_por_chave: dict[str, list[Path]],
) -> dict:
    """Constrói o JSON Silver completo para uma empresa."""
    cnpj = normaliza_cnpj(empresa["cnpj"])
    cod_cvm = empresa["cod_cvm"].strip()

    resultado = {
        "cnpj": cnpj,
        "cod_cvm": cod_cvm,
        "nome": empresa["nome"].strip(),
        "periodos": {},
    }

    # Acumula dados por período e demonstração
    # estrutura: { periodo: { "DFP"/"ITR": { "BPA": {cd: dados}, ... } } }
    dados: dict[str, dict] = defaultdict(lambda: {"tipo": None, "demonstracoes": {}})

    for chave, csvs in sorted(csvs_por_chave.items()):
        tipo_doc, tabela = chave.split("/")   # "dfp", "BPA"
        chave_dem = TABELA_PARA_CHAVE.get(tabela)
        if not chave_dem:
            continue

        for csv_path in csvs:
            linhas = ler_csv_cvm(csv_path)
            por_periodo = processar_linhas(linhas, cod_cvm)

            for periodo, contas in por_periodo.items():
                if not contas:
                    continue

                tipo_upper = tipo_doc.upper()  # "DFP" ou "ITR"
                dados[periodo]["tipo"] = tipo_upper

                dem = dados[periodo]["demonstracoes"]

                # DFC: só registra se ainda não tem (MD tem prioridade sobre MI)
                if chave_dem == "DFC" and "DFC" in dem:
                    continue

                dem[chave_dem] = contas

    # Ordena períodos do mais recente para o mais antigo
    for periodo in sorted(dados.keys(), reverse=True):
        resultado["periodos"][periodo] = dados[periodo]

    return resultado


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Parser Silver: CSVs filtrados → JSON por empresa."
    )
    parser.add_argument(
        "--cnpj",
        help="Processar só esta empresa (CNPJ, apenas dígitos)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Força reprocessamento mesmo que o arquivo já exista e esteja atualizado",
    )
    args = parser.parse_args()

    import os
    import time

    SILVER.mkdir(parents=True, exist_ok=True)

    empresas = carregar_empresas()
    if args.cnpj:
        cnpj_filtro = normaliza_cnpj(args.cnpj)
        empresas = [e for e in empresas if normaliza_cnpj(e.get("cnpj", "")) == cnpj_filtro]
        if not empresas:
            print(f"Empresa com CNPJ {args.cnpj} não encontrada em empresas_abertas.csv")
            return

    csvs_por_chave = descobrir_csvs_filtrados()

    print(f"\n{'='*60}")
    print("  credit-data-dl — Parser Silver")
    print(f"{'='*60}")
    print(f"  Empresas: {len(empresas)}")
    print(f"  Conjuntos de CSV encontrados: {len(csvs_por_chave)}")
    for chave, csvs in sorted(csvs_por_chave.items()):
        print(f"    {chave}: {len(csvs)} arquivo(s)")
    print()

    for empresa in empresas:
        cnpj = normaliza_cnpj(empresa.get("cnpj", ""))
        nome = empresa.get("nome", "").strip()
        cod_cvm = empresa.get("cod_cvm", "").strip()

        if not cnpj:
            print(f"  PULANDO {nome} — cnpj ausente")
            continue

        print(f"  Processando: {nome[:55]}", end="  ")

        # 1. Tenta CVM
        json_empresa = construir_json_empresa(empresa, csvs_por_chave)
        n_periodos_cvm = len(json_empresa["periodos"])

        # 2. Sempre tenta manual para mesclar/complementar
        manual_dados = carregar_manual_dados(cnpj)
        if manual_dados:
            n_manual = len(manual_dados.get("periodos", {}))
            print(f"(CVM: {n_periodos_cvm} per. + Manual: {n_manual} per.)", end=" ")
            # Mescla dados manuais (Manual tem prioridade sobre CVM se houver conflito)
            for periodo, dados in manual_dados.get("periodos", {}).items():
                json_empresa["periodos"][periodo] = dados
        else:
            print(f"(CVM: {n_periodos_cvm} períodos)", end=" ")

        n_periodos = len(json_empresa["periodos"])
        if n_periodos == 0:
            print("→ PULANDO")
            continue

        saida = SILVER / cnpj / f"{cnpj}.json"
        
        # ── [INCREMENTAL] Check ──────────────────────────────────────────────
        if not args.force and saida.exists() and not args.dry_run:
            mtime_saida = os.path.getmtime(saida)
            
            # Coleta mtime de todos os CSVs que afetam esta empresa
            mtimes_origem = []
            for chave, csvs in csvs_por_chave.items():
                for c_path in csvs:
                    mtimes_origem.append(os.path.getmtime(c_path))
            
            # Mtime do manual
            manual_path = MANUAL_UPLOADS / cnpj / f"{cnpj}.json"
            if manual_path.exists():
                mtimes_origem.append(os.path.getmtime(manual_path))
            
            if mtimes_origem and mtime_saida > max(mtimes_origem):
                print(f"→ ATUALIZADO (pulando)")
                continue

        if not args.dry_run:
            saida.parent.mkdir(parents=True, exist_ok=True)
            with open(saida, "w", encoding="utf-8") as f:
                json.dump(json_empresa, f, ensure_ascii=False, indent=2)
            print(f"→ Salvo: {cnpj}/{cnpj}.json")

    if args.dry_run:
        print("\n[dry-run] Nenhum arquivo foi salvo.")
    else:
        arquivos = list(SILVER.rglob("*.json"))
        print(f"\nConcluído! {len(arquivos)} arquivo(s) em {SILVER}")
        print("\nPróximo passo: python scripts/06_parser_silver_anbima.py")


if __name__ == "__main__":
    main()
