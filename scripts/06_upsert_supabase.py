"""
06_upsert_supabase.py

Lê os JSONs da camada Silver e o empresas_abertas.csv
e popula as tabelas do Supabase:
  - emissores
  - demonstracoes_master
  - operacoes (dados ANBIMA)

Pré-requisitos:
  pip install supabase python-dotenv

Configuração:
  Crie um arquivo .env na raiz do projeto com:
    SUPABASE_URL=https://xxxx.supabase.co
    SUPABASE_KEY=sua_service_role_key

  A service_role key está em:
  Supabase → Settings → API → service_role (não a anon key)

Uso:
  python 06_upsert_supabase.py                    # tudo
  python 06_upsert_supabase.py --cnpj 08827501000158  # só uma empresa
  python 06_upsert_supabase.py --apenas emissores  # só a tabela de emissores
  python 06_upsert_supabase.py --dry-run           # mostra sem salvar
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

# ── Configuração ─────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
SILVER       = PROJETO_RAIZ / "data" / "02_silver"
ANBIMA_DIR   = PROJETO_RAIZ / "data" / "01_landing" / "anbima"
EMPRESAS_CSV = SCRIPT_DIR / "empresas_abertas.csv"
ENV_FILE     = PROJETO_RAIZ / ".env"

# Tamanho do lote para insert em batch
BATCH_SIZE = 500

# ── Helpers ───────────────────────────────────────────────────────────────────

def carregar_env():
    """Carrega variáveis do .env se existir."""
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for linha in f:
                linha = linha.strip()
                if linha and not linha.startswith("#") and "=" in linha:
                    chave, valor = linha.split("=", 1)
                    os.environ.setdefault(chave.strip(), valor.strip())


def conectar_supabase():
    """Retorna cliente Supabase autenticado."""
    try:
        from supabase import create_client
    except ImportError:
        print("ERRO: supabase não instalado.")
        print("Execute: pip install supabase python-dotenv")
        sys.exit(1)

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()

    if not url or not key:
        print("ERRO: SUPABASE_URL e SUPABASE_KEY não encontrados.")
        print(f"Crie o arquivo {ENV_FILE} com:")
        print("  SUPABASE_URL=https://xxxx.supabase.co")
        print("  SUPABASE_KEY=sua_service_role_key")
        sys.exit(1)

    return create_client(url, key)


def normaliza_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj)


def carregar_empresas() -> list[dict]:
    with open(EMPRESAS_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def carregar_json_silver(cnpj: str) -> dict | None:
    path = SILVER / f"{cnpj}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def carregar_anbima(ticker: str) -> dict | None:
    path = ANBIMA_DIR / ticker / "caracteristicas.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def batches(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


# ── Upsert emissores ──────────────────────────────────────────────────────────

def upsert_emissores(supabase, empresas: list[dict], dry_run: bool):
    print("\n── Emissores ──")
    registros = []
    for e in empresas:
        cnpj = normaliza_cnpj(e.get("cnpj", ""))
        if not cnpj:
            print(f"  PULANDO {e.get('nome', '?')} — sem CNPJ")
            continue
        registros.append({
            "cnpj":          cnpj,
            "cod_cvm":       e.get("cod_cvm", "").strip() or None,
            "nome":          e.get("nome", "").strip(),
            "categoria_cvm": e.get("categoria", "").strip() or None,
            "ticker_acao":   e.get("ticker_acao", "").strip() or None,
            "observacao":    e.get("observacao", "").strip() or None,
        })

    print(f"  {len(registros)} emissores para upsert")
    if dry_run:
        for r in registros:
            print(f"    {r['cnpj']}  {r['nome'][:50]}")
        return

    resp = supabase.table("emissores").upsert(
        registros,
        on_conflict="cnpj",
    ).execute()
    print(f"  OK — {len(registros)} registros inseridos/atualizados")


# ── Upsert demonstracoes_master ───────────────────────────────────────────────

def upsert_demonstracoes(supabase, cnpj: str, dados: dict, dry_run: bool) -> int:
    """Converte JSON Silver → linhas da demonstracoes_master e faz upsert."""
    registros = []

    for periodo, periodo_dados in dados.get("periodos", {}).items():
        tipo_doc = periodo_dados.get("tipo", "?")
        for dem_nome, contas in periodo_dados.get("demonstracoes", {}).items():
            for cd_conta, conta in contas.items():
                registros.append({
                    "cnpj":         cnpj,
                    "data_ref":     periodo,
                    "tipo_doc":     tipo_doc,
                    "demonstracao": dem_nome,
                    "cd_conta":     cd_conta,
                    "ds_conta":     conta.get("ds_conta"),
                    "valor":        conta.get("valor"),
                })

    if not registros:
        return 0

    if dry_run:
        print(f"    {len(registros)} linhas (dry-run)")
        return len(registros)

    total = 0
    for lote in batches(registros, BATCH_SIZE):
        supabase.table("demonstracoes_master").upsert(
            lote,
            on_conflict="cnpj,data_ref,tipo_doc,demonstracao,cd_conta",
        ).execute()
        total += len(lote)

    return total


# ── Upsert operacoes (ANBIMA) ─────────────────────────────────────────────────

TICKERS_POR_CNPJ = {
    # Mapeamento ticker → CNPJ do emissor
    # Empresas abertas
    "ALAR14": "23438929000100",
    "CONX12": "23438929000100",
    "CASN34": "82508433000117",
    "CASN24": "82508433000117",
    "ERDVC4": "08873873000110",
    "ENAT33": "11669021000110",
    "IGSS11": "08159965000133",
    "IGSS21": "08159965000133",
    "IVIAA0": "02919555000167",
    "AEGE17": "15385166000140",
    "AEGPB5": "08827501000158",
    "RSAN26": "92802784000190",
    # Empresas fechadas (CNPJ a preencher quando cadastradas)
    "BTEL13": None,
    "BTEL33": None,
    "CLTM14": None,
    "COMR15": None,
    "HGLB13": None,
    "HGLB23": None,
    "HVSP11": None,
    "IRJS15": None,
    "ISPE12": None,
    "ORIG12": None,
    "QMCT14": None,
    "RALM11": None,
    "RGRA11": None,
    "RIS422": None,
    "RISP22": None,
    "RMSA12": None,
    "SABP12": None,
    "SGAB11": None,
    "SVEA16": None,
    "UNEG11": None,
    "CJEN13": None,
    "BRKP28": None,
    "SCPT13": None,
    "CCIA23": None,
}


def upsert_operacoes(supabase, dry_run: bool):
    print("\n── Operações (ANBIMA) ──")
    registros = []

    for ticker, cnpj in TICKERS_POR_CNPJ.items():
        if not cnpj:
            continue  # fechadas ainda sem CNPJ cadastrado

        dados_anbima = carregar_anbima(ticker)
        if not dados_anbima:
            continue

        # Extrai campos principais do payload ANBIMA
        # A estrutura exata varia — guardamos o payload completo em dados_anbima
        # e extraímos o que conseguirmos
        registro = {
            "cnpj":          normaliza_cnpj(cnpj),
            "ticker_deb":    ticker,
            "tipo":          "debenture",
            "dados_anbima":  dados_anbima,
        }

        # Tenta extrair campos estruturados do payload
        if isinstance(dados_anbima, dict):
            registro["data_emissao"]    = dados_anbima.get("dataEmissao") or dados_anbima.get("data_emissao")
            registro["data_vencimento"] = dados_anbima.get("dataVencimento") or dados_anbima.get("data_vencimento")
            registro["volume_emissao"]  = dados_anbima.get("valorEmissao") or dados_anbima.get("volume_emissao")
            registro["indexador"]       = dados_anbima.get("indexador")
            registro["rating_emissao"]  = dados_anbima.get("rating")

        registros.append(registro)

    print(f"  {len(registros)} operações com dados ANBIMA disponíveis")

    if not registros:
        print("  Nenhum dado ANBIMA encontrado — execute 03_download_anbima.py primeiro")
        return

    if dry_run:
        for r in registros:
            print(f"    {r['ticker_deb']}  {r['cnpj']}")
        return

    for lote in batches(registros, BATCH_SIZE):
        supabase.table("operacoes").upsert(
            lote,
            on_conflict="ticker_deb",
        ).execute()

    print(f"  OK — {len(registros)} operações inseridas/atualizadas")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Upsert Silver → Supabase"
    )
    parser.add_argument("--cnpj", help="Processar só esta empresa")
    parser.add_argument(
        "--apenas",
        choices=["emissores", "demonstracoes", "operacoes"],
        help="Processar só esta tabela",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    carregar_env()

    print("\n" + "=" * 60)
    print("  credit-data-dl — Upsert Supabase")
    print("=" * 60)

    if args.dry_run:
        print("  MODO DRY-RUN — nenhum dado será salvo\n")
        supabase = None
    else:
        supabase = conectar_supabase()
        print("  Conexão Supabase: OK\n")

    empresas = carregar_empresas()
    if args.cnpj:
        cnpj_filtro = normaliza_cnpj(args.cnpj)
        empresas = [e for e in empresas if normaliza_cnpj(e.get("cnpj","")) == cnpj_filtro]

    # ── Emissores ──
    if not args.apenas or args.apenas == "emissores":
        upsert_emissores(supabase, empresas, args.dry_run)

    # ── Demonstrações ──
    if not args.apenas or args.apenas == "demonstracoes":
        print("\n── Demonstrações financeiras ──")
        total_linhas = 0
        for empresa in empresas:
            cnpj = normaliza_cnpj(empresa.get("cnpj", ""))
            nome = empresa.get("nome", "?")[:50]
            if not cnpj:
                continue

            dados = carregar_json_silver(cnpj)
            if not dados:
                print(f"  {nome}: sem JSON Silver — pulando")
                continue

            n_periodos = len(dados.get("periodos", {}))
            print(f"  {nome}: {n_periodos} períodos", end="  ")

            n = upsert_demonstracoes(supabase, cnpj, dados, args.dry_run)
            total_linhas += n
            if not args.dry_run:
                print(f"→ {n} linhas")

        print(f"\n  Total: {total_linhas} linhas inseridas/atualizadas")

    # ── Operações ──
    if not args.apenas or args.apenas == "operacoes":
        upsert_operacoes(supabase, args.dry_run)

    print("\n" + "=" * 60)
    print("  Concluído!")
    if not args.dry_run:
        print("  Verifique no Supabase → Table Editor")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
