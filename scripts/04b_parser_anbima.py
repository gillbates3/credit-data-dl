"""
04b_parser_anbima.py

Lê os JSONs brutos de 01_landing/anbima/{TICKER}/
e faz upsert direto nas tabelas do Supabase:
  - operacoes        (campos descritivos da emissão)
  - agenda_pagamentos (fluxo de eventos)
  - pu_historico     (série temporal de PU)

Os JSONs brutos são os arquivos gerados pelo seu scraper ANBIMA,
salvos com a estrutura:
  01_landing/anbima/{TICKER}/caracteristicas.json
  01_landing/anbima/{TICKER}/agenda.json          (array de eventos)
  01_landing/anbima/{TICKER}/pu_historico.json    (fotografia atual)
  01_landing/anbima/{TICKER}/grafico_pu.json      (série temporal — opcional)

Uso:
  python 04b_parser_anbima.py
  python 04b_parser_anbima.py --ticker ALAR14
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

BATCH_SIZE = 500

# Mapeamento ticker → CNPJ do emissor (mesmo do script 06)
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


def to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return None


def to_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def batches(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def descobrir_tickers() -> list[str]:
    """Lista tickers com pelo menos caracteristicas.json na landing zone."""
    encontrados = []
    for pasta in sorted(ANBIMA_DIR.iterdir()):
        if pasta.is_dir() and (pasta / "caracteristicas.json").exists():
            encontrados.append(pasta.name)
    return encontrados


# ── Parser: operacoes ─────────────────────────────────────────────────────────

def parsear_operacao(ticker: str, carac: dict) -> dict:
    """Extrai campos estruturados do JSON de características."""
    emissao = carac.get("emissao", {}) or {}
    emissor = emissao.get("emissor", {}) or {}
    coord   = emissao.get("coordenador_lider", {}) or {}
    agente  = emissao.get("agente_fiduciario", {}) or {}
    indexador = carac.get("indexador", {}) or {}

    cnpj_emissor = normaliza_cnpj(
        emissor.get("cnpj") or TICKERS_POR_CNPJ.get(ticker) or ""
    )

    # Infere lei_incentivo a partir dos campos lei/artigo
    lei_incentivo = None
    if carac.get("lei"):
        artigo = carac.get("artigo", "")
        if "2" in str(artigo):
            lei_incentivo = "Lei 12.431 - Art. 2º"
        else:
            lei_incentivo = "Lei 12.431"

    return {
        "ticker_deb":               ticker,
        "cnpj":                     cnpj_emissor or None,
        "nome_emissor":             emissor.get("nome") or carac.get("emissor"),
        "tipo":                     "debenture",
        "isin":                     carac.get("isin"),
        "serie":                    carac.get("numero_serie"),
        "data_emissao":             emissao.get("data_emissao"),
        "data_vencimento":          carac.get("data_vencimento"),
        "data_primeiro_pagamento":  carac.get("data_inicio_rentabilidade"),
        "volume_emissao":           to_float(emissao.get("volume") or carac.get("volume")),
        "valor_unitario_emissao":   to_float(carac.get("vne")),
        "quantidade_debentures":    to_int(emissao.get("quantidade_emitida") or carac.get("quantidade_emitida")),
        "indexador":                indexador.get("nome") or carac.get("indexador"),
        "spread_emissao":           to_float(carac.get("taxa_emissao")),
        "especie":                  emissao.get("garantia"),
        "lei_incentivo":            lei_incentivo,
        "banco_coordenador":        coord.get("nome") or coord.get("razao_social"),
        "banco_liquidante":         emissao.get("banco_mandatario"),
        "agente_fiduciario":        agente.get("nome") or agente.get("razao_social"),
        "prazo_anos":               None,   # calculado se necessário
        "dados_anbima":             carac,   # payload completo como fallback
        "status":                   "ativo",
    }


# ── Parser: agenda_pagamentos ─────────────────────────────────────────────────

def parsear_agenda(ticker: str, cnpj: str, eventos: list) -> list[dict]:
    """Converte array de eventos da agenda em registros para o Supabase."""
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
            "taxa":            to_float(ev.get("taxa")),
            "valor":           to_float(ev.get("valor")),
            "status":          status_obj.get("status") if isinstance(status_obj, dict) else ev.get("status"),
            "grupo_status":    status_obj.get("grupo_status") if isinstance(status_obj, dict) else None,
        })
    return registros


# ── Parser: pu_historico ──────────────────────────────────────────────────────

def parsear_pu(ticker: str, pu_atual: dict, grafico: list | None) -> list[dict]:
    """
    Combina pu_historico (fotografia atual) com grafico_pu (série temporal).
    Retorna lista de registros para upsert.
    """
    registros_por_data: dict[str, dict] = {}

    # Fotografia atual do endpoint pu_historico
    if pu_atual:
        data = pu_atual.get("data_referencia")
        if data:
            registros_por_data[data] = {
                "ticker_deb":               ticker,
                "data_referencia":          data,
                "pu_par":                   to_float(pu_atual.get("pu_par")),
                "vna":                      to_float(pu_atual.get("vna")),
                "juros":                    to_float(pu_atual.get("juros")),
                "prazo_remanescente":       to_int(pu_atual.get("prazo_remanescente")),
                "pu_indicativo":            None,
                "flag_status":              pu_atual.get("flag_status"),
                "data_ultima_atualizacao":  str(pu_atual.get("data_ultima_atualizacao", ""))[:10] or None,
            }

    # Série temporal do endpoint grafico-pu-historico-indicativo
    if grafico:
        # Pode vir como lista direta ou sob a chave "pus"
        serie = grafico if isinstance(grafico, list) else grafico.get("pus", [])
        for ponto in serie:
            data = ponto.get("data")
            if not data:
                continue
            if data not in registros_por_data:
                registros_por_data[data] = {
                    "ticker_deb":         ticker,
                    "data_referencia":    data,
                    "pu_par":             None,
                    "vna":                None,
                    "juros":              None,
                    "prazo_remanescente": None,
                    "flag_status":        None,
                    "data_ultima_atualizacao": None,
                }
            registros_por_data[data]["pu_indicativo"] = to_float(
                ponto.get("valor_pu_indicativo")
            )
            # Se também tiver pu_historico no gráfico, preenche pu_par
            if ponto.get("valor_pu_historico") and not registros_por_data[data].get("pu_par"):
                registros_por_data[data]["pu_par"] = to_float(ponto.get("valor_pu_historico"))

    return list(registros_por_data.values())


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
    print(f"  Tickers encontrados: {len(tickers)}")
    print(f"  Tabelas: {args.apenas or 'todas'}\n")

    stats = {"operacoes": 0, "agenda": 0, "pu": 0, "sem_cnpj": 0}

    for ticker in tickers:
        pasta = ANBIMA_DIR / ticker
        print(f"  {ticker}:", end="  ")

        # Carrega os JSONs disponíveis
        carac   = carregar_json(pasta / "caracteristicas.json")
        agenda  = carregar_json(pasta / "agenda.json")
        pu_atual = carregar_json(pasta / "pu_historico.json")
        grafico = carregar_json(pasta / "grafico_pu.json")

        if not carac:
            print("sem caracteristicas.json — pulando")
            continue

        # Resolve CNPJ
        emissao  = carac.get("emissao", {}) or {}
        emissor  = emissao.get("emissor", {}) or {}
        cnpj = normaliza_cnpj(
            emissor.get("cnpj") or TICKERS_POR_CNPJ.get(ticker) or ""
        )
        if not cnpj:
            print("AVISO: CNPJ não encontrado — adicionar em TICKERS_POR_CNPJ")
            stats["sem_cnpj"] += 1
            continue

        partes = []

        # ── operacoes ──
        if not args.apenas or args.apenas == "operacoes":
            op = parsear_operacao(ticker, carac)
            if not args.dry_run:
                supabase.table("operacoes").upsert(
                    op, on_conflict="ticker_deb"
                ).execute()
            stats["operacoes"] += 1
            partes.append("op:OK")

        # ── agenda ──
        if not args.apenas or args.apenas == "agenda":
            eventos_raw = agenda
            if isinstance(agenda, dict):
                eventos_raw = agenda.get("content", [])
            if eventos_raw:
                registros_ag = parsear_agenda(ticker, cnpj, eventos_raw)
                if not args.dry_run and registros_ag:
                    for lote in batches(registros_ag, BATCH_SIZE):
                        supabase.table("agenda_pagamentos").upsert(
                            lote,
                            on_conflict="ticker_deb,data_evento,evento",
                        ).execute()
                stats["agenda"] += len(eventos_raw)
                partes.append(f"agenda:{len(eventos_raw)}")
            else:
                partes.append("agenda:0")

        # ── pu_historico ──
        if not args.apenas or args.apenas == "pu":
            if pu_atual or grafico:
                registros_pu = parsear_pu(ticker, pu_atual or {}, grafico)
                if not args.dry_run and registros_pu:
                    for lote in batches(registros_pu, BATCH_SIZE):
                        supabase.table("pu_historico").upsert(
                            lote,
                            on_conflict="ticker_deb,data_referencia",
                        ).execute()
                stats["pu"] += len(registros_pu)
                partes.append(f"pu:{len(registros_pu)}")
            else:
                partes.append("pu:0")

        print("  ".join(partes))

    print(f"\n{'=' * 60}")
    print(f"  Operações processadas:  {stats['operacoes']}")
    print(f"  Eventos de agenda:      {stats['agenda']}")
    print(f"  Pontos de PU:           {stats['pu']}")
    if stats["sem_cnpj"]:
        print(f"  Sem CNPJ (verificar):   {stats['sem_cnpj']}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
