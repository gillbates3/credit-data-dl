"""
04b_parser_anbima.py

Lê os JSONs brutos de 01_landing/anbima/{TICKER}/ produzidos pelo
scraper (03_download_anbima.py) e faz upsert nas tabelas do Supabase:

  operacoes         ← caracteristicas.json
  agenda_pagamentos ← agenda.json        (.content[])
  pu_historico      ← grafico_pu.json    (.pus[])        — série completa de PU
                    + pu_historico.json  (.content[])    — adiciona vna/juros
                    + precos.json        (.precos[])      — adiciona taxas/duration

Arquivos esperados por ticker em 01_landing/anbima/{TICKER}/:
  caracteristicas.json
  agenda.json
  pu_historico.json
  grafico_pu.json
  precos.json

Uso:
  python 04b_parser_anbima.py
  python 04b_parser_anbima.py --ticker CASN34
  python 04b_parser_anbima.py --dry-run
  python 04b_parser_anbima.py --apenas operacoes
  python 04b_parser_anbima.py --apenas agenda
  python 04b_parser_anbima.py --apenas pu
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


# ── Parser: pu_historico ──────────────────────────────────────────────────────

def parsear_pu(
    ticker: str,
    grafico_json: dict | None,
    pu_hist_json: dict | None,
    precos_json: dict | None,
) -> list[dict]:
    """
    Consolida três fontes numa série histórica única por data.

    Fontes e campos que cada uma contribui:
      grafico_pu.json   → pus[]:    pu_par (valor_pu_historico), pu_indicativo (valor_pu_indicativo)
      pu_historico.json → content[]: pu_par, vna, juros, flag_status
      precos.json       → precos[]:  taxa_indicativa, taxa_compra, taxa_venda,
                                     duration, percentual_pu_par, desvio_padrao,
                                     reune, intervalo_min/max, referencia_ntnb
    """
    por_data: dict[str, dict] = {}

    def base(data: str) -> dict:
        return {
            "ticker_deb":               ticker,
            "data_referencia":          data,
            "pu_par":                   None,
            "vna":                      None,
            "juros":                    None,
            "prazo_remanescente":       None,
            "pu_indicativo":            None,
            "taxa_indicativa":          None,
            "taxa_compra":              None,
            "taxa_venda":               None,
            "duration_dias_uteis":      None,
            "percentual_pu_par":        None,
            "percentual_vne":           None,
            "desvio_padrao":            None,
            "reune":                    None,
            "intervalo_indicativo_min": None,
            "intervalo_indicativo_max": None,
            "referencia_ntnb":          None,
            "pu_indicativo_status":     None,
            "taxa_indicativa_status":   None,
            "flag_status":              None,
            "data_ultima_atualizacao":  None,
        }

    # 1. grafico_pu.json → série completa de PU par + PU indicativo
    if grafico_json:
        for ponto in grafico_json.get("pus", []):
            data = ponto.get("data")
            if not data:
                continue
            r = por_data.setdefault(data, base(data))
            r["pu_par"]       = f(ponto.get("valor_pu_historico"))
            r["pu_indicativo"] = f(ponto.get("valor_pu_indicativo"))

    # 2. pu_historico.json → adiciona vna, juros, flag_status por dia
    if pu_hist_json:
        for item in pu_hist_json.get("content", []):
            data = item.get("data_referencia")
            if not data:
                continue
            r = por_data.setdefault(data, base(data))
            if r["pu_par"] is None:
                r["pu_par"] = f(item.get("pu_par"))
            r["vna"]                = f(item.get("vna"))
            r["juros"]              = f(item.get("juros"))
            r["prazo_remanescente"] = i(item.get("prazo_remanescente"))
            r["flag_status"]        = item.get("flag_status")
            r["data_ultima_atualizacao"] = data_curta(item.get("data_ultima_atualizacao"))

    # 3. precos.json → adiciona taxas e mercado secundário (dias recentes)
    if precos_json:
        for item in precos_json.get("precos", []):
            data = item.get("data_referencia")
            if not data:
                continue
            r = por_data.setdefault(data, base(data))
            r["taxa_indicativa"]          = f(item.get("taxa_indicativa"))
            r["taxa_compra"]              = f(item.get("taxa_compra"))
            r["taxa_venda"]               = f(item.get("taxa_venda"))
            r["duration_dias_uteis"]      = i(item.get("duration"))
            r["percentual_pu_par"]        = f(item.get("percentual_pu_par"))
            r["percentual_vne"]           = f(item.get("percentual_vne"))
            r["desvio_padrao"]            = f(item.get("desvio_padrao"))
            r["reune"]                    = f(item.get("reune"))
            r["intervalo_indicativo_min"] = f(item.get("intervalo_indicativo_minimo"))
            r["intervalo_indicativo_max"] = f(item.get("intervalo_indicativo_maximo"))
            r["referencia_ntnb"]          = item.get("data_referencia_ntnb")
            r["pu_indicativo_status"]     = item.get("pu_indicativo_status")
            r["taxa_indicativa_status"]   = item.get("taxa_indicativa_status")
            if r["data_ultima_atualizacao"] is None:
                r["data_ultima_atualizacao"] = data_curta(item.get("data_ultima_atualizacao"))
            # pu_indicativo do precos confirma o do grafico
            if r["pu_indicativo"] is None:
                r["pu_indicativo"] = f(item.get("pu_indicativo"))

        # fotografia atual de pu_historico (objeto raiz do precos.json)
        ph = precos_json.get("pu_historico") or {}
        data_ph = ph.get("data_referencia")
        if data_ph:
            r = por_data.setdefault(data_ph, base(data_ph))
            if r["pu_par"] is None:
                r["pu_par"] = f(ph.get("pu_par"))
            if r["vna"] is None:
                r["vna"] = f(ph.get("vna"))
            if r["juros"] is None:
                r["juros"] = f(ph.get("juros"))
            if r["prazo_remanescente"] is None:
                r["prazo_remanescente"] = i(ph.get("prazo_remanescente"))

    return list(por_data.values())


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Parser ANBIMA: JSONs brutos → Supabase"
    )
    parser.add_argument("--ticker", help="Processar só este ticker")
    parser.add_argument(
        "--apenas",
        choices=["operacoes", "agenda", "pu"],
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

    stats = {"operacoes": 0, "agenda": 0, "pu": 0, "sem_cnpj": 0, "erros": 0}

    for ticker in tickers:
        pasta = ANBIMA_DIR / ticker
        print(f"  {ticker:<10}", end="  ")

        carac      = carregar_json(pasta / "caracteristicas.json")
        agenda_j   = carregar_json(pasta / "agenda.json")
        pu_hist_j  = carregar_json(pasta / "pu_historico.json")
        grafico_j  = carregar_json(pasta / "grafico_pu.json")
        precos_j   = carregar_json(pasta / "precos.json")

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
                    supabase.table("operacoes").upsert(
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
                            supabase.table("agenda_pagamentos").upsert(
                                lote,
                                on_conflict="ticker_deb,data_evento,evento",
                            ).execute()
                    stats["agenda"] += len(regs)
                    partes.append(f"agenda:{len(regs)}")
                else:
                    partes.append("agenda:—")

            # ── pu_historico ──
            if not args.apenas or args.apenas == "pu":
                if grafico_j or pu_hist_j or precos_j:
                    regs = parsear_pu(ticker, grafico_j, pu_hist_j, precos_j)
                    if not args.dry_run and regs:
                        for lote in batches(regs, BATCH_SIZE):
                            supabase.table("pu_historico").upsert(
                                lote,
                                on_conflict="ticker_deb,data_referencia",
                            ).execute()
                    stats["pu"] += len(regs)
                    partes.append(f"pu:{len(regs)}")
                else:
                    partes.append("pu:—")

        except Exception as e:
            print(f"ERRO: {e}")
            stats["erros"] += 1
            continue

        print("  ".join(partes))

    print(f"\n{'='*60}")
    print(f"  Operações:        {stats['operacoes']}")
    print(f"  Eventos agenda:   {stats['agenda']}")
    print(f"  Pontos PU:        {stats['pu']}")
    if stats["sem_cnpj"]:
        print(f"  Sem CNPJ:         {stats['sem_cnpj']}")
    if stats["erros"]:
        print(f"  Erros:            {stats['erros']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()