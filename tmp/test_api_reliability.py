"""Teste de confiabilidade da API - 5 tickers REAIS do portfolio."""
import time
import httpx

BASE = "http://localhost:8000"
KEY = "dev_credit_data_dl_2026_chave_longa_mosquetao"
HEADERS = {"X-API-Key": KEY, "Content-Type": "application/json"}

# Tickers reais do emissoes.csv do projeto
TICKERS = ["RALM21", "RIS412", "RISP12", "CGOSA2", "SABP12"]

resultados = []

for ticker in TICKERS:
    print(f"\n{'='*60}")
    print(f"  Testando: {ticker}")
    print(f"{'='*60}")

    r = httpx.post(f"{BASE}/ingest/ticker", json={"ticker": ticker}, headers=HEADERS)
    if r.status_code != 202:
        print(f"  ERRO ao criar job: {r.status_code} {r.text}")
        resultados.append({"ticker": ticker, "status": "ERRO_POST", "detalhes": r.text})
        continue

    job_id = r.json()["job_id"]
    print(f"  Job criado: {job_id}")

    inicio = time.time()
    status_final = None
    job_data = None
    while time.time() - inicio < 120:
        time.sleep(3)
        jr = httpx.get(f"{BASE}/jobs/{job_id}", headers=HEADERS)
        job_data = jr.json()
        st = job_data["status"]
        etapa = job_data.get("etapa_atual", "?")
        elapsed = time.time() - inicio
        print(f"  [{elapsed:.0f}s] status={st} etapa={etapa}")
        if st in ("concluido", "concluido_com_erros", "erro"):
            status_final = st
            break
    else:
        status_final = "TIMEOUT"

    tempo_total = time.time() - inicio
    progresso = job_data.get("progresso", {}) if job_data else {}
    erros = progresso.get("erros", [])
    passos = progresso.get("passos_concluidos", [])

    resultados.append({
        "ticker": ticker,
        "status": status_final,
        "tempo_s": round(tempo_total, 1),
        "passos": passos,
        "erros": erros,
        "periodos_cvm": progresso.get("periodos_cvm", 0),
        "dias_historico": progresso.get("dias_historico", 0),
        "eventos_agenda": progresso.get("eventos_agenda", 0),
    })

    print(f"  >> Resultado: {status_final} em {tempo_total:.1f}s")
    if erros:
        for e in erros:
            print(f"  >> ERRO: {e}")

# Resumo
print(f"\n\n{'='*60}")
print(f"  RESUMO FINAL - {len(TICKERS)} tickers testados")
print(f"{'='*60}")
sucesso = sum(1 for r in resultados if r["status"] == "concluido")
com_erros = sum(1 for r in resultados if r["status"] == "concluido_com_erros")
falhas = sum(1 for r in resultados if r["status"] in ("erro", "ERRO_POST", "TIMEOUT"))

print(f"\n  [OK] Sucesso:          {sucesso}/{len(TICKERS)}")
print(f"  [!!] Com erros:        {com_erros}/{len(TICKERS)}")
print(f"  [XX] Falhas:           {falhas}/{len(TICKERS)}")
print(f"  Taxa de sucesso:       {(sucesso + com_erros) / len(TICKERS) * 100:.0f}%")
print()

for r in resultados:
    emoji = "[OK]" if r["status"] == "concluido" else "[!!]" if r["status"] == "concluido_com_erros" else "[XX]"
    print(f"  {emoji} {r['ticker']:10s} | {r['status']:22s} | {r.get('tempo_s', '?'):>6}s | CVM={r.get('periodos_cvm',0)} Hist={r.get('dias_historico',0)} Agenda={r.get('eventos_agenda',0)}")
    if r.get("erros"):
        for e in r["erros"]:
            print(f"       -> {e}")
