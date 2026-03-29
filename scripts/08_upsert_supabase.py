"""
08_upsert_supabase.py

Lê o Dossiê do Emissor (Camada Silver) e popula o Supabase:
  - emissores
  - demonstracoes_financeiras (Balanços)
  - deb_caracteristicas      (ANBIMA Caracteristicas)
  - deb_agenda               (ANBIMA Agenda)
  - deb_historico_diario     (ANBIMA Preços)

Uso:
  python scripts/08_upsert_supabase.py
  python scripts/08_upsert_supabase.py --cnpj 23438929000100
  python scripts/08_upsert_supabase.py --dry-run
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
EMPRESAS_CSV = PROJETO_RAIZ / "empresas.csv"
EMISSOES_CSV = PROJETO_RAIZ / "emissoes.csv"
ENV_FILE     = PROJETO_RAIZ / ".env"

BATCH_SIZE = 500

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
        print("ERRO: pip install supabase python-dotenv")
        sys.exit(1)
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        print("ERRO: SUPABASE_URL e SUPABASE_KEY não encontrados no .env")
        sys.exit(1)
    return create_client(url, key)

def normaliza_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj or "")

def f(v) -> float | None:
    if v is None or v == "": return None
    try: return float(str(v).replace(",", "."))
    except: return None

def i(v) -> int | None:
    if v is None or v == "": return None
    try: return int(float(str(v)))
    except: return None

def batches(lst, n):
    for idx in range(0, len(lst), n):
        yield lst[idx:idx + n]

# ── Carregamento de Dados ─────────────────────────────────────────────────────

def carregar_cadastro_empresas() -> list[dict]:
    if not EMPRESAS_CSV.exists(): return []
    with open(EMPRESAS_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def carregar_mapa_emissoes() -> dict[str, list[str]]:
    """Retorna { cnpj: [ticker1, ticker2] }."""
    mapa = {}
    if not EMISSOES_CSV.exists(): return mapa
    with open(EMISSOES_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "").strip()
            cnpj = normaliza_cnpj(row.get("cnpj_emissor", ""))
            if ticker and cnpj:
                mapa.setdefault(cnpj, []).append(ticker)
    return mapa

# ── Upserts ───────────────────────────────────────────────────────────────────

def upsert_emissores(supabase, empresas: list[dict], dry_run: bool):
    print("\n── [1] Emissores ──")
    registros = []
    for e in empresas:
        cnpj = normaliza_cnpj(e.get("cnpj", ""))
        if not cnpj: continue
        registros.append({
            "cnpj":          cnpj,
            "cod_cvm":       e.get("cod_cvm", "").strip() or None,
            "nome":          e.get("nome", "").strip(),
            "categoria_cvm": e.get("categoria", "").strip() or None,
            "ticker_acao":   e.get("ticker_acao", "").strip() or None,
            "observacao":    e.get("observacao", "").strip() or None,
        })
    
    if not registros: return
    print(f"  {len(registros)} registros")
    if not dry_run:
        supabase.table("emissores").upsert(registros, on_conflict="cnpj").execute()

def upsert_financeiro(supabase, cnpj: str, dry_run: bool):
    path = SILVER / cnpj / f"{cnpj}.json"
    if not path.exists(): return 0
    
    with open(path, encoding="utf-8") as f_in:
        dados = json.load(f_in)
        
    registros = []
    for periodo, p_dados in dados.get("periodos", {}).items():
        tipo_doc = p_dados.get("tipo", "?")
        for dem, contas in p_dados.get("demonstracoes", {}).items():
            for cd, c_dados in contas.items():
                registros.append({
                    "cnpj":         cnpj,
                    "data_ref":     periodo,
                    "tipo_doc":     tipo_doc,
                    "demonstracao": dem,
                    "cd_conta":     cd,
                    "ds_conta":     c_dados.get("ds_conta"),
                    "valor":        c_dados.get("valor"),
                })
                
    if not registros: return 0
    if not dry_run:
        for lote in batches(registros, BATCH_SIZE):
            supabase.table("demonstracoes_financeiras").upsert(
                lote, on_conflict="cnpj,data_ref,tipo_doc,demonstracao,cd_conta"
            ).execute()
    return len(registros)

def upsert_anbima_ticker(supabase, cnpj: str, ticker: str, dry_run: bool) -> dict:
    pasta = SILVER / cnpj / "anbima" / ticker
    res = {"op": 0, "agenda": 0, "hist": 0}
    
    # 1. Caracteristicas (Operações)
    carac_path = pasta / "caracteristicas.json"
    if carac_path.exists():
        with open(carac_path, encoding="utf-8") as f_in:
            c = json.load(f_in)
            emissao = c.get("emissao") or {}
            emissor = emissao.get("emissor") or {}
            indexador_obj = c.get("indexador") or {}
            
            # Parsing de Remuneração (Indexador + Taxa Pré)
            remun_str = c.get("remuneracao", "")
            indexador_nome = indexador_obj.get("nome") if isinstance(indexador_obj, dict) else str(indexador_obj)
            taxa_pre = None
            
            if not indexador_nome or indexador_nome == "None":
                # Tenta extrair da string de remuneração: "IPCA + 5,5%" ou "100% do CDI"
                match = re.search(r"(\w+)\s*\+\s*([\d\.,]+)%", remun_str)
                if match:
                    indexador_nome = match.group(1).strip().upper()
                    taxa_pre = f(match.group(2))
                else:
                    match_cdi = re.search(r"([\d\.,]+)%\s*do\s*(\w+)", remun_str, re.IGNORECASE)
                    if match_cdi:
                        indexador_nome = match_cdi.group(2).strip().upper()
                        taxa_pre = f(match_cdi.group(1))

            coord_lider = emissao.get("coordenador_lider") or {}
            agf = emissao.get("agente_fiduciario") or {}
            
            # Cálculos Adicionais
            vol_emissao = f(emissao.get("volume") or c.get("volume"))
            qtd_emissao = i(emissao.get("quantidade_emitida"))
            pu_emissao = None
            if vol_emissao and qtd_emissao:
                pu_emissao = vol_emissao / qtd_emissao

            # Prazo da emissão em anos
            prazo_anos = None
            d_emissao = emissao.get("data_emissao")
            d_vencim = c.get("data_vencimento")
            if d_emissao and d_vencim:
                try:
                    from datetime import datetime
                    dt_e = datetime.strptime(d_emissao, "%Y-%m-%d")
                    dt_v = datetime.strptime(d_vencim, "%Y-%m-%d")
                    prazo_anos = round((dt_v - dt_e).days / 365.25, 2)
                except:
                    pass

            reg_op = {
                "ticker_deb":              ticker,
                "cnpj":                    cnpj,
                "nome_emissor":            emissor.get("nome"),
                "tipo":                    "debenture",
                "isin":                    c.get("isin"),
                "serie":                   c.get("numero_serie"),
                "numero_emissao":          i(emissao.get("numero_emissao")),
                "data_emissao":            d_emissao,
                "data_vencimento":         d_vencim,
                "data_primeiro_pagamento": None, # Pode ser extraído da agenda futuramente
                "prazo_anos":              prazo_anos,
                "volume_emissao":          vol_emissao,
                "valor_unitario_emissao":  pu_emissao,
                "quantidade_debentures":    qtd_emissao,
                "indexador":               indexador_nome,
                "taxa_prefixada":          taxa_pre or f(c.get("taxa_emissao")),
                "especie":                 emissao.get("garantia"),
                "lei_incentivo":           "Sim" if c.get("lei") else "Não",
                "banco_coordenador":       coord_lider.get("nome") or coord_lider.get("razao_social"),
                "agente_fiduciario":       agf.get("nome") or agf.get("razao_social"),
                "banco_liquidante":        emissao.get("banco_mandatario"),
                "status":                  "ativo",
                "dados_anbima":            c,
            }

            if not dry_run:
                supabase.table("deb_caracteristicas").upsert(reg_op, on_conflict="ticker_deb").execute()
            res["op"] = 1

    # 2. Agenda
    agenda_path = pasta / "agenda.json"
    if agenda_path.exists():
        with open(agenda_path, encoding="utf-8") as f_in:
            data = json.load(f_in)
            eventos = data.get("content", []) if isinstance(data, dict) else data
            regs = []
            for ev in eventos:
                if not ev.get("data_evento"): continue
                regs.append({
                    "ticker_deb":      ticker,
                    "cnpj":            cnpj,
                    "data_evento":     ev.get("data_evento"),
                    "data_base":       ev.get("data_base"),
                    "data_liquidacao": ev.get("data_liquidacao"),
                    "evento":          ev.get("evento"),
                    "evento_arc":      ev.get("evento_arc"),
                    "taxa":            f(ev.get("taxa")),
                    "valor":           f(ev.get("valor")),
                    "status":          ev.get("status", {}).get("status") if isinstance(ev.get("status"), dict) else str(ev.get("status")),
                    "grupo_status":    ev.get("status", {}).get("grupo_status") if isinstance(ev.get("status"), dict) else None
                })
            if regs and not dry_run:
                for lote in batches(regs, BATCH_SIZE):
                    supabase.table("deb_agenda").upsert(lote, on_conflict="ticker_deb,data_evento,evento").execute()
            res["agenda"] = len(regs)

    # 3. Histórico Diário
    hist_path = pasta / "historico_diario.json"
    if hist_path.exists():
        with open(hist_path, encoding="utf-8") as f_in:
            data = json.load(f_in)
            regs_brutos = data if isinstance(data, list) else data.get("dados", [])
            regs = []
            for r in regs_brutos:
                if not r.get("data_referencia"): continue
                regs.append({
                    "ticker_deb":              ticker,
                    "data_referencia":         r.get("data_referencia"),
                    "pu_par":                  f(r.get("pu_par")),
                    "vna":                     f(r.get("vna")),
                    "juros":                   f(r.get("juros")),
                    "prazo_remanescente":      i(r.get("prazo_remanescente")),
                    "pu_indicativo":           f(r.get("pu_indicativo")),
                    "taxa_indicativa":         f(r.get("taxa_indicativa")),
                    "taxa_compra":             f(r.get("taxa_compra")),
                    "taxa_venda":              f(r.get("taxa_venda")),
                    "duration_dias_uteis":     f(r.get("duration_dias_uteis")),
                    "desvio_padrao":           f(r.get("desvio_padrao")),
                    "percentual_pu_par":       f(r.get("percentual_pu_par")),
                    "percentual_vne":          f(r.get("percentual_vne")),
                    "intervalo_indicativo_min": f(r.get("intervalo_indicativo_min")),
                    "intervalo_indicativo_max": f(r.get("intervalo_indicativo_max")),
                    "referencia_ntnb":         r.get("referencia_ntnb"),
                    "spread_indicativo":       f(r.get("spread_indicativo")),
                    "volume_financeiro":       f(r.get("volume_financeiro")),
                    "quantidade_negocios":     i(r.get("quantidade_negocios")),
                    "quantidade_titulos":      i(r.get("quantidade_titulos")),
                    "taxa_media_negocios":     f(r.get("taxa_media_negocios")),
                    "pu_medio_negocios":       f(r.get("pu_medio_negocios")),
                    "reune":                   r.get("reune"),
                    "percentual_reune":        f(r.get("percentual_reune")),
                    "pu_indicativo_status":    r.get("pu_indicativo_status"),
                    "taxa_indicativa_status":  r.get("taxa_indicativa_status"),
                    "flag_status":             r.get("flag_status"),
                    "data_ultima_atualizacao": r.get("data_ultima_atualizacao"),
                })
            if regs and not dry_run:
                for lote in batches(regs, BATCH_SIZE):
                    supabase.table("deb_historico_diario").upsert(lote, on_conflict="ticker_deb,data_referencia").execute()
            res["hist"] = len(regs)
    
    return res

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Upsert Silver Dossier → Supabase")
    parser.add_argument("--cnpj", help="Processar só este CNPJ")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    carregar_env()
    supabase = None if args.dry_run else conectar_supabase()

    print("\n" + "=" * 60)
    print(f"  credit-data-dl — Upsert Supabase {'[DRY-RUN]' if args.dry_run else ''}")
    print("=" * 60)

    # 1. Cadastro Base
    empresas = carregar_cadastro_empresas()
    if args.cnpj:
        target = normaliza_cnpj(args.cnpj)
        empresas = [e for e in empresas if normaliza_cnpj(e.get("cnpj")) == target]
    
    upsert_emissores(supabase, empresas, args.dry_run)

    # 2. Dossiês Silver
    mapa_tickers = carregar_mapa_emissoes()
    
    print("\n── [2] Dossiês (Financeiro + ANBIMA) ──")
    for e in empresas:
        cnpj = normaliza_cnpj(e.get("cnpj"))
        nome = e.get("nome", "?")[:40]
        print(f"  {cnpj} | {nome}")
        
        # Financeiro
        n_fin = upsert_financeiro(supabase, cnpj, args.dry_run)
        if n_fin: print(f"    Financeiro: {n_fin} linhas")
        
        # ANBIMA Tickers
        tickers = mapa_tickers.get(cnpj, [])
        for t in tickers:
            stats = upsert_anbima_ticker(supabase, cnpj, t, args.dry_run)
            if any(stats.values()):
                print(f"    Ticker {t:<7}: op:{stats['op']} agenda:{stats['agenda']} hist:{stats['hist']}")

    print(f"\n{'='*60}\n  Concluído!\n{'='*60}\n")

if __name__ == "__main__":
    main()
