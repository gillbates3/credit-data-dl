"""Verifica se o banco foi preenchido corretamente pelos testes."""
from scripts_v2 import servico_repositorio as repo

TICKERS = ["RALM21", "RIS412", "RISP12", "CGOSA2", "SABP12", "PETR26"]

print("=" * 80)
print("  VERIFICACAO DO BANCO DE DADOS")
print("=" * 80)

# 1. Emissores
print("\n--- EMISSORES ---")
emissores_encontrados = 0
for t in TICKERS:
    # Buscar via portfolio/view
    pass

# Usar a API para portfolio
import httpx
BASE = "http://localhost:8000"
KEY = "dev_credit_data_dl_2026_chave_longa_mosquetao"
H = {"X-API-Key": KEY}

r = httpx.get(f"{BASE}/portfolio", headers=H)
portfolio = r.json()
print(f"\nPortfolio total: {len(portfolio)} debentures")
for item in portfolio:
    ticker = item.get("ticker_deb", "?")
    nome = item.get("nome", "?")[:45]
    status = item.get("status", "?")
    indexador = item.get("indexador", "?")
    venc = item.get("data_vencimento", "?")
    print(f"  {ticker:10s} | {nome:45s} | {status:6s} | {indexador:6s} | venc={venc}")

# 2. Proximos pagamentos
print(f"\n--- PROXIMOS PAGAMENTOS ---")
r2 = httpx.get(f"{BASE}/proximos-pagamentos", headers=H)
pgtos = r2.json()
print(f"Total: {len(pgtos)} eventos futuros")
if pgtos:
    for p in pgtos[:5]:
        print(f"  {p.get('ticker_deb','?'):10s} | {p.get('data_evento','?')} | {p.get('evento','?')}")
    if len(pgtos) > 5:
        print(f"  ... e mais {len(pgtos)-5}")

# 3. Historico por ticker (via API emissores)
print(f"\n--- EMISSORES COM DEBENTURES ---")
# Pegar CNPJs unicos do portfolio
cnpjs = set()
for item in portfolio:
    cnpj = item.get("cnpj", "")
    if cnpj:
        cnpjs.add(cnpj)

for cnpj in sorted(cnpjs):
    r3 = httpx.get(f"{BASE}/emissores/{cnpj}", headers=H)
    if r3.status_code == 200:
        data = r3.json()
        emissor = data.get("emissor", {})
        debs = data.get("debentures", [])
        nome = emissor.get("nome", "?")[:50]
        tipo = emissor.get("tipo_capital", "?")
        cod = emissor.get("cod_cvm") or "sem CVM"
        print(f"  {cnpj} | {nome:50s} | {tipo:8s} | {cod}")
        for d in debs:
            print(f"    -> {d.get('ticker_deb','?'):10s} | idx={d.get('indexador','?')} | venc={d.get('data_vencimento','?')}")
    else:
        print(f"  {cnpj} | ERRO {r3.status_code}")

# 4. Jobs recentes
print(f"\n--- JOBS RECENTES ---")
r4 = httpx.get(f"{BASE}/jobs", headers=H)
jobs = r4.json()
print(f"Total: {len(jobs)} jobs")
for j in jobs[:10]:
    jid = j.get("id","")[:8]
    alvo = j.get("alvo","?")
    st = j.get("status","?")
    eta = j.get("etapa_atual","?")
    print(f"  {jid}... | {alvo:10s} | {st:22s} | etapa={eta}")

# 5. Contagens diretas via repositorio
print(f"\n--- CONTAGENS DIRETAS (repositorio) ---")
for cnpj in sorted(cnpjs):
    hq = repo.buscar_hashes_quantitativo(cnpj)
    hql = repo.buscar_hashes_qualitativo(cnpj)
    pd = repo.buscar_periodos_demonstracoes(cnpj)
    emissor = repo.buscar_emissor(cnpj)
    nome = emissor.get("nome","?")[:30] if emissor else "?"
    print(f"  {cnpj} ({nome:30s}) | periodos_dem={len(pd)} | hashes_quant={len(hq)} | hashes_qual={len(hql)}")

print(f"\n{'='*80}")
print("  FIM DA VERIFICACAO")
print(f"{'='*80}")
