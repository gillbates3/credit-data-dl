"""
06_consolidacao_anbima_silver.py

Lê os JSONs brutos de 01_landing/anbima/{TICKER}/ e organiza na camada
Silver seguindo a hierarquia por CNPJ:
  02_silver/{CNPJ}/anbima/{TICKER}/

Uso:
  python scripts/06_parser_silver_anbima.py
"""

import csv
import json
import shutil
from pathlib import Path

# ── Configuração ─────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
LANDING_ANBIMA = PROJETO_RAIZ / "data" / "01_landing" / "anbima"
SILVER         = PROJETO_RAIZ / "data" / "02_silver"
EMISSOES_CSV   = PROJETO_RAIZ / "emissoes.csv"

# ── Helpers ───────────────────────────────────────────────────────────────────

def carregar_mapa_emissoes() -> dict[str, str]:
    """Mapeia ticker -> cnpj_emissor a partir do emissoes.csv."""
    mapa = {}
    if not EMISSOES_CSV.exists():
        return mapa
        
    with open(EMISSOES_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "").strip()
            cnpj = "".join(c for c in row.get("cnpj_emissor", "") if c.isdigit())
            if ticker and cnpj:
                mapa[ticker] = cnpj
    return mapa

def descobrir_tickers_landing() -> list[str]:
    """Lista tickers com dados na landing zone."""
    if not LANDING_ANBIMA.exists():
        return []
    return [p.name for p in LANDING_ANBIMA.iterdir() if p.is_dir()]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("  credit-data-dl — Consolidação ANBIMA → Silver")
    print("=" * 60)

    mapa_emissoes = carregar_mapa_emissoes()
    tickers = descobrir_tickers_landing()
    
    if not tickers:
        print("  Nenhum dado encontrado em data/01_landing/anbima/")
        return

    print(f"  Encontrados {len(tickers)} tickers na Landing Zone.")
    print(f"  Mapeamento emissoes.csv: {len(mapa_emissoes)} vínculos.\n")

    cont_sucesso = 0
    cont_pula = 0

    for ticker in tickers:
        cnpj = mapa_emissoes.get(ticker)
        if not cnpj:
            print(f"  {ticker:<10} → PULANDO (CNPJ não vinculado em emissoes.csv)")
            cont_pula += 1
            continue

        origem = LANDING_ANBIMA / ticker
        destino = SILVER / cnpj / "anbima" / ticker
        
        destino.mkdir(parents=True, exist_ok=True)
        
        arquivos = ["caracteristicas.json", "agenda.json", "historico_diario.json"]
        copiados = []
        
        for arq in arquivos:
            arq_origem = origem / arq
            arq_destino = destino / arq
            if arq_origem.exists():
                import os
                # [INCREMENTAL] Só copia se for diferente (mtime ou size)
                pula = False
                if arq_destino.exists():
                    stats_o = arq_origem.stat()
                    stats_d = arq_destino.stat()
                    # Diferença de até 1s na mtime é ignorada (FAT32/zip issues)
                    if abs(stats_o.st_mtime - stats_d.st_mtime) < 1.0 and stats_o.st_size == stats_d.st_size:
                        pula = True
                
                if not pula:
                    shutil.copy2(arq_origem, arq_destino)
                    copiados.append(arq)
        
        print(f"  {ticker:<10} → {cnpj}  ({len(copiados)} arquivos)")
        cont_sucesso += 1

    print(f"\n{'='*60}")
    print(f"  Consolidados: {cont_sucesso}")
    print(f"  Pulados:      {cont_pula}")
    print(f"  Destino:      data/02_silver/{{CNPJ}}/anbima/")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()