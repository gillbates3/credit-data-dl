"""Testes de inserção de documentos (DFs e não-DFs) para Paranaguá Saneamento S.A. (PASN12)"""
import httpx
import time
import sys
from pathlib import Path

BASE = "http://localhost:8000"
KEY = "dev_credit_data_dl_2026_chave_longa_mosquetao"
HEADERS = {"X-API-Key": KEY}

# Client com timeout de 60 segundos para evitar timeouts na API
client = httpx.Client(timeout=60.0, headers=HEADERS)

CNPJ_PARANAGUA = "01691945000160"
MANUAL_UPLOADS_DIR = Path(r"C:\Dev\Antigravity\credit-data-dl\data\01_landing\manual_uploads\igua\Paranagua Saneamento S A")

print("=" * 80)
print("  INICIANDO INGESTÃO E TESTE DE DOCUMENTOS - PARANAGUÁ SANEAMENTO")
print("=" * 80)

# Função auxiliar para monitorar jobs
def wait_for_job(job_id, max_wait_sec=360):
    start = time.time()
    print(f"  Monitorando Job {job_id}...")
    while time.time() - start < max_wait_sec:
        time.sleep(3)
        try:
            r = client.get(f"{BASE}/jobs/{job_id}")
            job = r.json()
            st = job.get("status")
            etapa = job.get("etapa_atual", "?")
            print(f"    - [{time.time() - start:.0f}s] status={st} | etapa={etapa}")
            if st in ("concluido", "concluido_com_erros", "erro", "falhado"):
                return job
        except Exception as e:
            print(f"    - Erro ao obter status do job: {e}")
    raise TimeoutError(f"Job {job_id} excedeu o tempo limite de {max_wait_sec}s.")

# STEP 1: Ingerir ticker PASN12 para criar o emissor e dados de mercado
print("\n--- PASSO 1: Ingerir ticker PASN12 ---")
r_ticker = client.post(f"{BASE}/ingest/ticker", json={"ticker": "PASN12", "deep": False})
if r_ticker.status_code != 202:
    print(f"Erro ao disparar ingestão de PASN12: {r_ticker.status_code} - {r_ticker.text}")
    sys.exit(1)

job_ticker_id = r_ticker.json()["job_id"]
job_ticker = wait_for_job(job_ticker_id)
print(f"Ingestão do ticker concluída com status: {job_ticker['status']}")
prog_ticker = job_ticker.get("progresso", {})
print(f"  Eventos de agenda encontrados: {prog_ticker.get('eventos_agenda')}")
print(f"  Histórico diário (dias): {prog_ticker.get('dias_historico')}")

# STEP 2: Iterar e fazer upload de TODOS os PDFs da pasta
print("\n--- PASSO 2: Ingestão de todos os PDFs da pasta de uploads manuais ---")
if not MANUAL_UPLOADS_DIR.exists():
    print(f"Erro: Pasta {MANUAL_UPLOADS_DIR} não localizada!")
    sys.exit(1)

pdf_files = list(MANUAL_UPLOADS_DIR.glob("*.pdf"))
print(f"Encontrados {len(pdf_files)} arquivos PDF para processar.")

for pdf_file in sorted(pdf_files):
    nome_arquivo = pdf_file.name
    print(f"\n>> Enviando: {nome_arquivo} ({pdf_file.stat().st_size / 1024 / 1024:.2f} MB)...")
    with open(pdf_file, "rb") as f:
        files = [("arquivos", (nome_arquivo, f.read(), "application/pdf"))]
    
    r = client.post(
        f"{BASE}/ingest/documentos",
        data={"cnpj": CNPJ_PARANAGUA},
        files=files
    )
    if r.status_code != 202:
        print(f"  Erro ao disparar upload de {nome_arquivo}: {r.status_code} - {r.text}")
        continue
        
    job_id = r.json()["job_id"]
    job = wait_for_job(job_id)
    print(f"  Upload de {nome_arquivo} concluído com status: {job['status']}")
    print(f"  Progresso detalhado: {job.get('progresso')}")

print("\n" + "=" * 80)
print("  TESTES CONCLUÍDOS!")
print("=" * 80)
