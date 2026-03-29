"""
04b_parser_anbima.py

Lê os JSONs brutos de 01_landing/anbima/{TICKER}/ produzidos pelo
scraper (03_download_anbima.py) e faz upsert nas tabelas do Supabase:

  operacoes         ← caracteristicas.json
  agenda_pagamentos ← agenda.json        
  historico_diario  ← historico_diario.json

Arquivos esperados por ticker em 01_landing/anbima/{TICKER}/:
  caracteristicas.json
  agenda.json
  historico_diario.json

Uso:
  python 04b_parser_anbima.py
  python 04b_parser_anbima.py --ticker CASN34
  python 04b_parser_anbima.py --dry-run
  python 04b_parser_anbima.py --apenas operacoes
  python 04b_parser_anbima.py --apenas agenda
  python 04b_parser_anbima.py --apenas historico
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
ANBIMA_DIR   = PROJETO_RAIZ / "data" / "01_landing" / "anbima"
ENV_FILE     = PROJETO_RAIZ / ".env"
BATCH_SIZE   = 500

TICKERS_POR_CNPJ = {
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
    # fechadas — CNPJ a preencher quando cadastradas
    "BTEL13": None, "BTEL33": None, "CLTM14": None, "COMR15": None,
    "HGLB13": None, "HGLB23": None, "HVSP11": None, "IRJS15": None,
    "ISPE12": None, "ORIG12": None, "QMCT14": None, "RALM11": None,
    "RGRA11": None, "RIS422": None, "RISP22": None, "RMSA12": None,
    "SABP12": None, "SGAB11": None, "SVEA16": None, "UNEG11": None,
    "CJEN13": None, "BRKP28": None, "SCPT13": None, "CCIA23": None,
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def carregar_env():
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for linha in f:
                linha = linha.strip()
                if linha and not linha.startswith("#") and "=" in linha:
                    k, v = linha.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def conectar_supabase():
    try:
        from supabase import create_client
    except ImportError:
        print("ERRO: pip install supabase")
        sys.exit(1)
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        print("ERRO: SUPABASE_URL e SUPABASE_KEY não encontrados no .env")
        sys.exit(1)
    return create_client(url, key)


def carregar_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def normaliza_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj or "")


def f(v) -> float | None:
    """Converte para float, tolerando None e strings vazias."""
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return None


def i(v) -> int | None:
    """Converte para int, tolerando None e strings vazias."""
    if v is None or v == "":
        return None
    try:
        return int(float(str(v)))
    except (ValueError, TypeError):
        return None


def data_curta(v) -> str | None:
    """Retorna só os 10 primeiros chars de uma string de data/datetime."""
    if not v:
        return None
    return str(v)[:10]


def batches(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def descobrir_tickers() -> list[str]:
    """Lista tickers com pelo menos caracteristicas.json na landing zone."""
    return sorted(
        p.name for p in ANBIMA_DIR.iterdir()
        if p.is_dir() and (p / "caracteristicas.json").exists()
    )


def resolver_cnpj(ticker: str, carac: dict) -> str | None:
    """Tenta resolver CNPJ a partir do JSON ou do mapeamento fixo."""
    emissao = carac.get("emissao") or {}
    emissor = emissao.get("emissor") or {}
    cnpj = normaliza_cnpj(emissor.get("cnpj") or "")
    if not cnpj:
        cnpj = normaliza_cnpj(TICKERS_POR_CNPJ.get(ticker) or "")
    return cnpj or None


# ── Parser: operacoes ─────────────────────────────────────────────────────────

def parsear_operacao(ticker: str, carac: dict) -> dict:
    emissao    = carac.get("emissao") or {}
    emissor    = emissao.get("emissor") or {}
    agente     = emissao.get("agente_fiduciario") or {}
    coord_lider = emissao.get("coordenador_lider") or {}
    indexador  = carac.get("indexador") or {}

    # coordenadores pode ser lista ou objeto — pega o líder como string
    coord_str = coord_lider.get("nome") or coord_lider.get("razao_social")
    if not coord_str:
        coords = emissao.get("coordenadores") or []
        if coords:
            coord_str = coords[0].get("nome")

    lei_incentivo = None
    if carac.get("lei"):
        artigo = str(carac.get("artigo", ""))
        lei_incentivo = f"Lei 12.431 - Art. {artigo}" if artigo else "Lei 12.431"

    return {
        "ticker_deb":               ticker,
        "cnpj":                     resolver_cnpj(ticker, carac),
        "nome_emissor":             emissor.get("nome"),
        "tipo":                     "debenture",
        "isin":                     carac.get("isin"),
        "serie":                    carac.get("numero_serie"),
        "numero_emissao":           i(emissao.get("numero_emissao")),
        "data_emissao":             emissao.get("data_emissao"),
        "data_vencimento":          carac.get("data_vencimento"),
        "data_primeiro_pagamento":  carac.get("data_inicio_rentabilidade"),
        "prazo_anos":               None,
        "volume_emissao":           f(emissao.get("volume") or carac.get("volume")),
        "valor_unitario_emissao":   f(carac.get("vne")),
        "quantidade_debentures":    i(emissao.get("quantidade_emitida") or carac.get("quantidade_emitida")),
        "indexador":                indexador.get("nome"),
        "spread_emissao":           f(carac.get("taxa_emissao")),
        "especie":                  emissao.get("garantia"),
        "lei_incentivo":            lei_incentivo,
        "banco_coordenador":        coord_str,
        "banco_liquidante":         emissao.get("banco_mandatario"),
        "agente_fiduciario":        agente.get("nome") or agente.get("razao_social"),
        "status":                   "ativo",
        "dados_anbima":             carac,
    }


# ── Parser: agenda_pagamentos ─────────────────────────────────────────────────

def parsear_agenda(ticker: str, cnpj: str, agenda_json: dict) -> list[dict]:
    """
    agenda.json tem estrutura paginada:
    { "content": [...eventos], "total_elements": N, ... }
    O scraper já captura a página completa.
    """
    eventos = agenda_json.get("content", [])
    if not eventos and isinstance(agenda_json, list):
        eventos = agenda_json  # fallback se vier como lista direta

    registros = []
    for ev in eventos:
        if not ev.get("data_evento"):
            continue
        status_obj = ev.get("status") or {}
        registros.append({
            "ticker_deb":      ticker,
            "cnpj":            cnpj,
            "data_evento":     ev.get("data_evento"),
            "data_liquidacao": ev.get("data_liquidacao"),
            "data_base":       ev.get("data_base"),
            "evento":          ev.get("evento"),
            "evento_arc":      ev.get("evento_arc"),
            "taxa":            f(ev.get("taxa")),
            "valor":           f(ev.get("valor")),
            "status":          status_obj.get("status") if isinstance(status_obj, dict) else None,
            "grupo_status":    status_obj.get("grupo_status") if isinstance(status_obj, dict) else None,
        })
    return registros


# ── Parser: historico_diario ──────────────────────────────────────────────────

def parsear_historico_diario(ticker: str, historico_json: list | dict) -> list[dict]:
    """
    O json historico_diario já vem consolidado nativamente pela landing zone.
    Garante o parser seguro apenas para certificar as tipagens pro Supabase.
    """
    registros = historico_json if isinstance(historico_json, list) else historico_json.get("dados", [])
    
    resultado = []
    for r in registros:
        if not r.get("data_referencia"):
            continue
        r["ticker_deb"] = ticker
        
        r["pu_par"] = f(r.get("pu_par"))
        r["vna"] = f(r.get("vna"))
        r["juros"] = f(r.get("juros"))
        r["prazo_remanescente"] = i(r.get("prazo_remanescente"))
        
        r["pu_indicativo"] = f(r.get("pu_indicativo"))
        r["taxa_indicativa"] = f(r.get("taxa_indicativa"))
        r["taxa_compra"] = f(r.get("taxa_compra"))
        r["taxa_venda"] = f(r.get("taxa_venda"))
        r["duration_dias_uteis"] = f(r.get("duration_dias_uteis"))
        r["desvio_padrao"] = f(r.get("desvio_padrao"))
        r["percentual_pu_par"] = f(r.get("percentual_pu_par"))
        r["percentual_vne"] = f(r.get("percentual_vne"))
        r["intervalo_indicativo_min"] = f(r.get("intervalo_indicativo_min"))
        r["intervalo_indicativo_max"] = f(r.get("intervalo_indicativo_max"))
        r["spread_indicativo"] = f(r.get("spread_indicativo"))
        
        r["volume_financeiro"] = f(r.get("volume_financeiro"))
        r["quantidade_negocios"] = i(r.get("quantidade_negocios"))
        r["quantidade_titulos"] = i(r.get("quantidade_titulos"))
        r["taxa_media_negocios"] = f(r.get("taxa_media_negocios"))
        r["pu_medio_negocios"] = f(r.get("pu_medio_negocios"))
        
        r["percentual_reune"] = f(r.get("percentual_reune"))
        
        resultado.append(r)
        
    return resultado


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Parser ANBIMA: JSONs brutos → Supabase"
    )
    parser.add_argument("--ticker", help="Processar só este ticker")
    parser.add_argument(
        "--apenas",
        choices=["operacoes", "agenda", "historico"],
        help="Processar só esta tabela",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    carregar_env()

    print("\n" + "=" * 60)
    print("  credit-data-dl — Parser ANBIMA")
    print("=" * 60)

    if args.dry_run:
        print("  MODO DRY-RUN\n")
        supabase = None
    else:
        supabase = conectar_supabase()
        print("  Conexão Supabase: OK\n")

    tickers = [args.ticker] if args.ticker else descobrir_tickers()
    print(f"  Tickers: {len(tickers)}  |  Tabelas: {args.apenas or 'todas'}\n")

    stats = {"operacoes": 0, "agenda": 0, "historico": 0, "sem_cnpj": 0, "erros": 0}

    for ticker in tickers:
        pasta = ANBIMA_DIR / ticker
        print(f"  {ticker:<10}", end="  ")

        carac       = carregar_json(pasta / "caracteristicas.json")
        agenda_j    = carregar_json(pasta / "agenda.json")
        historico_j = carregar_json(pasta / "historico_diario.json")

        if not carac:
            print("sem caracteristicas.json — pulando")
            continue

        cnpj = resolver_cnpj(ticker, carac)
        if not cnpj:
            print("CNPJ não encontrado — adicionar em TICKERS_POR_CNPJ")
            stats["sem_cnpj"] += 1
            continue

        partes = []

        try:
            # ── operacoes ──
            if not args.apenas or args.apenas == "operacoes":
                op = parsear_operacao(ticker, carac)
                if not args.dry_run:
                    supabase.table("deb_caracteristicas").upsert(
                        op, on_conflict="ticker_deb"
                    ).execute()
                stats["operacoes"] += 1
                partes.append("op:OK")

            # ── agenda_pagamentos ──
            if not args.apenas or args.apenas == "agenda":
                if agenda_j:
                    regs = parsear_agenda(ticker, cnpj, agenda_j)
                    if not args.dry_run and regs:
                        for lote in batches(regs, BATCH_SIZE):
                            supabase.table("deb_agenda").upsert(
                                lote,
                                on_conflict="ticker_deb,data_evento,evento",
                            ).execute()
                    stats["agenda"] += len(regs)
                    partes.append(f"agenda:{len(regs)}")
                else:
                    partes.append("agenda:—")

            # ── historico_diario ──
            if not args.apenas or args.apenas == "historico":
                if historico_j:
                    regs = parsear_historico_diario(ticker, historico_j)
                    if not args.dry_run and regs:
                        for lote in batches(regs, BATCH_SIZE):
                            supabase.table("deb_historico_diario").upsert(
                                lote,
                                on_conflict="ticker_deb,data_referencia",
                            ).execute()
                    stats["historico"] += len(regs)
                    partes.append(f"hist:{len(regs)}")
                else:
                    partes.append("hist:—")

        except Exception as e:
            print(f"ERRO: {e}")
            stats["erros"] += 1
            continue

        print("  ".join(partes))

    print(f"\n{'='*60}")
    print(f"  Operações:        {stats['operacoes']}")
    print(f"  Eventos agenda:   {stats['agenda']}")
    print(f"  Registros diários:{stats['historico']}")
    if stats["sem_cnpj"]:
        print(f"  Sem CNPJ:         {stats['sem_cnpj']}")
    if stats["erros"]:
        print(f"  Erros:            {stats['erros']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()