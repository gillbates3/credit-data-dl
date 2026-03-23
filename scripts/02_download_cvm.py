"""
02_download_cvm.py

Baixa DFP (anuais), ITR (trimestrais) e FRE (formulário de referência)
do Portal de Dados Abertos da CVM para as empresas em empresas_abertas.csv.

Estratégia:
  - DFP e ITR: arquivos ZIP anuais com CSVs estruturados (dados financeiros)
  - FRE: arquivos ZIP anuais com documentos do formulário de referência
  - Filtra por cod_cvm para baixar apenas o necessário

Estrutura de saída:
  data/01_landing/cvm_raw/dfp/YYYY/
  data/01_landing/cvm_raw/itr/YYYY/
  data/01_landing/cvm_raw/fre/YYYY/

Uso:
  python 02_download_cvm.py
  python 02_download_cvm.py --anos 2022 2023 2024     # anos específicos
  python 02_download_cvm.py --tipo dfp                # só DFP
  python 02_download_cvm.py --tipo itr --anos 2024    # ITR de 2024
"""

import argparse
import csv
import io
import re
import zipfile
from datetime import datetime
from pathlib import Path

import requests

# ── Configuração ─────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
LANDING = PROJETO_RAIZ / "data" / "01_landing" / "cvm_raw"
EMPRESAS_CSV = SCRIPT_DIR / "empresas_abertas.csv"

# Intervalo padrão de anos
ANO_INICIO = 2018
ANO_FIM = datetime.now().year

# URLs base dos dados abertos CVM
BASE_URL = {
    "dfp": "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/",
    "itr": "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/",
    "fre": "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/",
}

# Arquivos CSV dentro do ZIP de DFP/ITR que nos interessam
TABELAS_DFP_ITR = [
    "BPA",   # Balanço Patrimonial Ativo
    "BPP",   # Balanço Patrimonial Passivo
    "DRE",   # Demonstração de Resultado
    "DFC_MD", # Demonstração de Fluxo de Caixa — Método Direto
    "DFC_MI", # Demonstração de Fluxo de Caixa — Método Indireto
    "DVA",   # Demonstração do Valor Adicionado
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def carregar_empresas() -> list[dict]:
    with open(EMPRESAS_CSV, encoding="utf-8") as f:
        empresas = list(csv.DictReader(f))
    validas = [e for e in empresas if e.get("cod_cvm", "").strip()]
    if not validas:
        raise ValueError(
            "Nenhuma empresa com cod_cvm em empresas_abertas.csv. "
            "Execute 01_resolver_codigos_cvm.py primeiro."
        )
    return validas


def codigos_cvm(empresas: list[dict]) -> set[str]:
    # Retorna os codigos como estao — normalizacao feita dentro de filtrar_e_salvar_csv
    return {e["cod_cvm"].strip() for e in empresas}


def baixar_zip(url: str, destino: Path) -> bool:
    """Baixa um ZIP para destino. Retorna True se OK, False se não encontrado."""
    if destino.exists():
        print(f"    já existe, pulando: {destino.name}")
        return True
    try:
        resp = requests.get(url, timeout=120, stream=True)
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        destino.parent.mkdir(parents=True, exist_ok=True)
        with open(destino, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"    baixado: {destino.name} ({destino.stat().st_size / 1024:.0f} KB)")
        return True
    except requests.RequestException as e:
        print(f"    ERRO ao baixar {url}: {e}")
        return False


def filtrar_e_salvar_csv(
    zip_path: Path,
    tabela: str,
    cod_cvms: set[str],
    destino_dir: Path,
) -> int:
    """
    Extrai CSV de uma tabela do ZIP, filtra pelas empresas de interesse
    e salva versao filtrada. Retorna numero de linhas filtradas.

    Nomes reais dentro dos ZIPs da CVM:
      dfp_cia_aberta_BPA_con_2024.csv   (ano no final)
      itr_cia_aberta_DRE_con_2024.csv
    O script busca por substring da tabela, independente de posicao do ano.
    """
    destino_dir.mkdir(parents=True, exist_ok=True)
    arquivo_saida = destino_dir / f"{tabela}_con.csv"

    if arquivo_saida.exists():
        return -1  # ja processado

    def normaliza_cod(cod: str) -> str:
        s = cod.strip()
        return str(int(s)) if s.isdigit() else s

    cod_cvms_norm = {normaliza_cod(c) for c in cod_cvms}

    try:
        with zipfile.ZipFile(zip_path) as zf:
            nomes_zip = zf.namelist()

            # Busca por substring: "_BPA_con_" ou "_BPA_ind_" em qualquer posicao
            # Cobre: dfp_cia_aberta_BPA_con_2024.csv e formatos similares
            substrings_con = [f"_{tabela}_con_", f"_{tabela.lower()}_con_"]
            substrings_ind = [f"_{tabela}_ind_", f"_{tabela.lower()}_ind_"]

            encontrados_con = [
                n for n in nomes_zip
                if any(s in n for s in substrings_con)
            ]
            encontrados_ind = [
                n for n in nomes_zip
                if any(s in n for s in substrings_ind)
            ]

            # Prefere consolidado; fallback para individual
            encontrados = encontrados_con or encontrados_ind

            if not encontrados:
                return 0

            arquivo_zip = encontrados[0]

            with zf.open(arquivo_zip) as f:
                conteudo_csv = f.read().decode("latin-1")

            linhas = list(csv.DictReader(io.StringIO(conteudo_csv), delimiter=";"))
            filtradas = [
                l for l in linhas
                if normaliza_cod(l.get("CD_CVM", "")) in cod_cvms_norm
            ]

            if not filtradas:
                return 0

            with open(arquivo_saida, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=filtradas[0].keys())
                writer.writeheader()
                writer.writerows(filtradas)

            return len(filtradas)

    except (zipfile.BadZipFile, KeyError) as e:
        print(f"      AVISO: problema ao processar {zip_path.name}/{tabela}: {e}")
        return 0


# ── Download DFP / ITR ────────────────────────────────────────────────────────

def processar_dfp_itr(tipo: str, anos: list[int], cod_cvms: set[str]):
    """Baixa e filtra DFP ou ITR para os anos solicitados."""
    base = BASE_URL[tipo]
    landing_tipo = LANDING / tipo

    print(f"\n{'='*60}")
    print(f"  {tipo.upper()} — {len(anos)} anos | {len(cod_cvms)} empresas")
    print(f"{'='*60}")

    for ano in sorted(anos):
        nome_zip = f"{tipo}_cia_aberta_{ano}.zip"
        url = base + nome_zip
        zip_path = landing_tipo / str(ano) / nome_zip

        print(f"\n  Ano {ano}:")
        ok = baixar_zip(url, zip_path)
        if not ok:
            print(f"    ZIP não disponível para {ano} — pulando.")
            continue

        destino_csv = landing_tipo / str(ano) / "filtrado"
        total = 0
        for tabela in TABELAS_DFP_ITR:
            n = filtrar_e_salvar_csv(zip_path, tabela, cod_cvms, destino_csv)
            if n > 0:
                print(f"    {tabela}: {n} linhas filtradas → {destino_csv}/{tabela}.csv")
            elif n == -1:
                pass  # já existia
            # n == 0: tabela não tinha dados para as empresas — silencioso

        print(f"    Concluído: {ano}")


# ── Download FRE ──────────────────────────────────────────────────────────────

def processar_fre(anos: list[int], cod_cvms: set[str]):
    """
    Baixa FRE (Formulário de Referência).
    FRE contém dados qualitativos: descrição do negócio, fatores de risco,
    estrutura de capital, informações sobre emissões de dívida, etc.
    São arquivos ZIP com múltiplos CSVs por seção do formulário.
    """
    base = BASE_URL["fre"]
    landing_fre = LANDING / "fre"

    # Seções do FRE mais relevantes para análise de crédito
    secoes_relevantes = [
        "fre_cia_aberta_deb",          # debêntures emitidas
        "fre_cia_aberta_geral",         # informações gerais
        "fre_cia_aberta_neg_direto",    # negócios — descrição direta
        "fre_cia_aberta_grupo_eco",     # grupo econômico
        "fre_cia_aberta_fat_risco",     # fatores de risco
        "fre_cia_aberta_estrut_cap",    # estrutura de capital
        "fre_cia_aberta_divida_emp",    # empréstimos e financiamentos
        "fre_cia_aberta_coment_desemp", # comentários de desempenho
    ]

    print(f"\n{'='*60}")
    print(f"  FRE — {len(anos)} anos | {len(cod_cvms)} empresas")
    print(f"{'='*60}")

    for ano in sorted(anos):
        nome_zip = f"fre_cia_aberta_{ano}.zip"
        url = base + nome_zip
        zip_path = landing_fre / str(ano) / nome_zip

        print(f"\n  Ano {ano}:")
        ok = baixar_zip(url, zip_path)
        if not ok:
            print(f"    ZIP não disponível para {ano} — pulando.")
            continue

        destino_csv = landing_fre / str(ano) / "filtrado"
        try:
            with zipfile.ZipFile(zip_path) as zf:
                nomes_zip = zf.namelist()

            for secao in secoes_relevantes:
                # Tenta variações do nome do arquivo
                for nome in [f"{secao}.csv", f"{secao}_{ano}.csv"]:
                    n = filtrar_e_salvar_csv(zip_path, secao, cod_cvms, destino_csv)
                    if n > 0:
                        print(f"    {secao}: {n} linhas → {destino_csv}/{secao}.csv")
                    break

        except zipfile.BadZipFile:
            print(f"    ERRO: ZIP corrompido — {zip_path.name}")

        print(f"    Concluído: {ano}")


# ── Main ──────────────────────────────────────────────────────────────────────

def listar_zip(zip_path: str):
    """Utilitario: lista arquivos dentro de um ZIP baixado."""
    import zipfile as zf
    path = Path(zip_path)
    if not path.exists():
        print(f"Arquivo nao encontrado: {zip_path}")
        return
    with zf.ZipFile(path) as z:
        nomes = sorted(z.namelist())
    print(f"\n{len(nomes)} arquivos em {path.name}:\n")
    for n in nomes:
        print(f"  {n}")


def main():
    parser = argparse.ArgumentParser(
        description="Download de DFP, ITR e FRE da CVM para empresas de interesse."
    )
    parser.add_argument(
        "--tipo",
        choices=["dfp", "itr", "fre", "todos"],
        default="todos",
        help="Tipo de documento a baixar (padrao: todos)",
    )
    parser.add_argument(
        "--anos",
        nargs="+",
        type=int,
        default=list(range(ANO_INICIO, ANO_FIM + 1)),
        help=f"Anos a baixar (padrao: {ANO_INICIO} a {ANO_FIM})",
    )
    parser.add_argument(
        "--listar-zip",
        metavar="CAMINHO_ZIP",
        help="Lista arquivos dentro de um ZIP para inspecao (debug)",
    )
    args = parser.parse_args()

    if args.listar_zip:
        listar_zip(args.listar_zip)
        return

    print("\n" + "=" * 60)
    print("  credit-data-dl — Download CVM")
    print("=" * 60)
    print(f"  Tipo: {args.tipo}")
    print(f"  Anos: {min(args.anos)} a {max(args.anos)}")

    empresas = carregar_empresas()
    cod_cvms = codigos_cvm(empresas)

    print(f"  Empresas: {len(empresas)}")
    for e in empresas:
        print(f"    {e['cod_cvm']:>8}  {e['nome'][:55]}")
    print()

    tipos = (
        ["dfp", "itr", "fre"] if args.tipo == "todos" else [args.tipo]
    )

    for tipo in tipos:
        if tipo in ("dfp", "itr"):
            processar_dfp_itr(tipo, args.anos, cod_cvms)
        elif tipo == "fre":
            processar_fre(args.anos, cod_cvms)

    print("\n\nConcluído!")
    print(f"Dados salvos em: {LANDING}")
    print("\nPróximo passo: python 03_download_anbima.py")


if __name__ == "__main__":
    main()