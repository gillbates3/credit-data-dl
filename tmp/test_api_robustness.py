"""Testes de robustez, resiliência e casos de contorno da API."""
import httpx
import time
import uuid

BASE = "http://localhost:8000"
KEY = "dev_credit_data_dl_2026_chave_longa_mosquetao"
HEADERS = {"X-API-Key": KEY}

print("=" * 80)
print("  INICIANDO 5 TESTES DE ROBUSTEZ DA API")
print("=" * 80)

# Lista para armazenar resultados dos testes
test_results = []

def run_test(name, func):
    print(f"\n[TEST] {name}")
    print("-" * 50)
    try:
        func()
        print(f"  -> [PASSED]")
        test_results.append((name, "PASS", ""))
    except AssertionError as ae:
        print(f"  -> [FAILED] Assertion Error: {ae}")
        test_results.append((name, "FAIL", str(ae)))
    except Exception as e:
        print(f"  -> [FAILED] Unexpected Error: {e}")
        test_results.append((name, "FAIL", str(e)) )

# -------------------------------------------------------------------------
# TEST 1: Segurança, Validação e Casos de Contorno em /ingest/ticker
# -------------------------------------------------------------------------
def test_ticker_validation_and_auth():
    # 1. Sem API Key (deve retornar 401)
    r1 = httpx.post(f"{BASE}/ingest/ticker", json={"ticker": "SABP12"})
    assert r1.status_code == 401, f"Retornou {r1.status_code} ao invés de 401 para requisição sem API Key."
    assert "invalida ou ausente" in r1.text, "Mensagem de erro inesperada para falta de API Key."
    
    # 2. Com API Key errada (deve retornar 401)
    r2 = httpx.post(f"{BASE}/ingest/ticker", json={"ticker": "SABP12"}, headers={"X-API-Key": "errada"})
    assert r2.status_code == 401, f"Retornou {r2.status_code} para API Key errada."
    
    # 3. Ticker vazio/inválido (deve retornar 422 ou 400 dependendo do validador)
    r3 = httpx.post(f"{BASE}/ingest/ticker", json={"ticker": ""}, headers=HEADERS)
    assert r3.status_code in (400, 422), f"Retornou {r3.status_code} para ticker vazio."
    
    print("  - Validações de segurança e ticker vazio passaram com sucesso.")

run_test("Test 1: Auth & Ingest Ticker Boundary Conditions", test_ticker_validation_and_auth)

# -------------------------------------------------------------------------
# TEST 2: Ingestão de Documentos (Upload) - CNPJ Válido e Inválido
# -------------------------------------------------------------------------
def test_document_upload():
    # 1. Upload para CNPJ inexistente no banco
    cnpj_inexistente = "00000000000000"
    files = [("arquivos", ("dummy.pdf", b"%PDF-1.4 dummy content", "application/pdf"))]
    data = {"cnpj": cnpj_inexistente}
    
    r1 = httpx.post(f"{BASE}/ingest/documentos", data=data, files=files, headers=HEADERS)
    assert r1.status_code == 202, f"Ingestão de docs falhou ao criar o job (retornou {r1.status_code})."
    
    job_id_1 = r1.json()["job_id"]
    print(f"  - Job {job_id_1} criado para CNPJ inexistente. Monitorando...")
    
    # Espera o job terminar. Como o CNPJ não existe, o job deve falhar/dar erro.
    status_1 = None
    for _ in range(15):
        time.sleep(2)
        rj = httpx.get(f"{BASE}/jobs/{job_id_1}", headers=HEADERS)
        job_data = rj.json()
        status_1 = job_data["status"]
        if status_1 in ["erro", "falhado", "concluido", "concluido_com_erros"]:
            break
            
    assert status_1 in ["erro", "falhado"], f"Job de CNPJ inexistente deveria falhar, mas terminou como {status_1}."
    print("  - Ingestão para CNPJ inexistente falhou como esperado (resiliência confirmada).")
    
    # 2. Upload para CNPJ existente (SABP12: 42292007000174)
    cnpj_sabesp = "42292007000174"
    data_sabesp = {"cnpj": cnpj_sabesp}
    r2 = httpx.post(f"{BASE}/ingest/documentos", data=data_sabesp, files=files, headers=HEADERS)
    assert r2.status_code == 202, f"Falha ao criar job para CNPJ existente (SABP12)."
    
    job_id_2 = r2.json()["job_id"]
    print(f"  - Job {job_id_2} criado para CNPJ válido (SABP12). Monitorando...")
    
    status_2 = None
    for _ in range(15):
        time.sleep(2)
        rj = httpx.get(f"{BASE}/jobs/{job_id_2}", headers=HEADERS)
        job_data = rj.json()
        status_2 = job_data["status"]
        if status_2 in ["erro", "falhado", "concluido", "concluido_com_erros"]:
            break
            
    # Deve concluir (com erros ou concluído, porque enviamos um PDF dummy sem dados reais estruturados)
    assert status_2 in ["concluido", "concluido_com_erros"], f"Job de CNPJ válido terminou inesperadamente como {status_2}."
    print(f"  - Ingestão para CNPJ válido concluída com status esperado: {status_2}")

run_test("Test 2: Document Upload Ingestion (Valid & Invalid CNPJ)", test_document_upload)

# -------------------------------------------------------------------------
# TEST 3: Funcionamento Dia a Dia - Consistência de Portfolio e Pagamentos
# -------------------------------------------------------------------------
def test_portfolio_and_payments_consistency():
    # 1. Listar Portfolio
    r_port = httpx.get(f"{BASE}/portfolio", headers=HEADERS)
    assert r_port.status_code == 200, f"Falha ao buscar portfolio: {r_port.status_code}"
    portfolio = r_port.json()
    assert isinstance(portfolio, list), "Portfolio retornado não é uma lista."
    print(f"  - Portfolio atual contém {len(portfolio)} debêntures.")
    
    tickers_portfolio = {item["ticker_deb"] for item in portfolio}
    
    # 2. Listar Próximos Pagamentos
    r_pgtos = httpx.get(f"{BASE}/proximos-pagamentos", headers=HEADERS)
    assert r_pgtos.status_code == 200, f"Falha ao buscar próximos pagamentos: {r_pgtos.status_code}"
    pgtos = r_pgtos.json()
    assert isinstance(pgtos, list), "Próximos pagamentos não são uma lista."
    print(f"  - Próximos pagamentos contém {len(pgtos)} eventos.")
    
    # Verificar ordenação por data_evento e consistência dos tickers
    datas = []
    for p in pgtos:
        assert "ticker_deb" in p, "Evento de pagamento sem campo ticker_deb."
        assert "data_evento" in p, "Evento de pagamento sem campo data_evento."
        datas.append(p["data_evento"])
        
        # O ticker deve constar no portfolio
        # (nota: se o banco for resetado no meio, pode variar, mas no funcionamento diário deve bater)
        ticker = p["ticker_deb"]
        assert ticker in tickers_portfolio, f"Ticker {ticker} listado nos pagamentos não existe no portfolio."
        
    # Validar ordenação cronológica (datas crescentes)
    datas_ordenadas = sorted(datas)
    assert datas == datas_ordenadas, "Os próximos pagamentos não estão devidamente ordenados por data cronológica."
    print("  - Ordenação e consistência dos próximos pagamentos validadas com sucesso.")

run_test("Test 3: Portfolio & Upcoming Payments Consistency", test_portfolio_and_payments_consistency)

# -------------------------------------------------------------------------
# TEST 4: Busca de Emissores (Casos de Contorno e Validação de Formato)
# -------------------------------------------------------------------------
def test_get_emissor_details():
    # 1. CNPJ inexistente (deve retornar 404)
    cnpj_fake = "11111111111111"
    r_fake = httpx.get(f"{BASE}/emissores/{cnpj_fake}", headers=HEADERS)
    assert r_fake.status_code == 404, f"Esperava 404 para CNPJ fake, mas retornou {r_fake.status_code}."
    assert "Emissor nao encontrado" in r_fake.text, "Mensagem de erro inesperada para emissor fake."
    
    # 2. CNPJ válido de Sabesp (SABP12: 42292007000174)
    cnpj_real = "42292007000174"
    r_real = httpx.get(f"{BASE}/emissores/{cnpj_real}", headers=HEADERS)
    assert r_real.status_code == 200, f"Falha ao buscar emissor real: {r_real.status_code}"
    
    emissor_data = r_real.json()
    assert "emissor" in emissor_data, "Falta chave 'emissor' no JSON retornado."
    assert "debentures" in emissor_data, "Falta chave 'debentures' no JSON retornado."
    
    emissor = emissor_data["emissor"]
    debs = emissor_data["debentures"]
    
    assert emissor["cnpj"] == cnpj_real, f"CNPJ retornado ({emissor['cnpj']}) não bate com o buscado."
    assert len(debs) > 0, "Deveria haver pelo menos uma debênture associada à SABESP no banco."
    
    print(f"  - Emissor {emissor.get('nome')} localizado. {len(debs)} debênture(s) associada(s).")

run_test("Test 4: Get Issuer Details (Valid & Invalid CNPJ)", test_get_emissor_details)

# -------------------------------------------------------------------------
# TEST 5: Resiliência em Busca de Jobs Inexistentes
# -------------------------------------------------------------------------
def test_job_id_resilience():
    # 1. Buscar UUID de job inexistente (deve dar 404)
    random_uuid = str(uuid.uuid4())
    r1 = httpx.get(f"{BASE}/jobs/{random_uuid}", headers=HEADERS)
    assert r1.status_code == 404, f"Esperava 404 para Job ID randômico, retornou {r1.status_code}."
    assert "Job nao encontrado" in r1.text, "Mensagem de erro inesperada para Job ID fake."
    
    # 2. Buscar formato inválido de ID (caso de contorno)
    invalid_id = "job-invalido-123"
    r2 = httpx.get(f"{BASE}/jobs/{invalid_id}", headers=HEADERS)
    assert r2.status_code == 404, f"Esperava 404 para ID de formato inválido, retornou {r2.status_code}."
    
    print("  - Busca de Jobs inexistentes tratada com resiliência (404 Retornado).")

run_test("Test 5: Resiliency to Non-existent Job Lookups", test_job_id_resilience)

# -------------------------------------------------------------------------
# RESUMO FINAL
# -------------------------------------------------------------------------
print("\n" + "=" * 80)
print("  RESUMO FINAL DOS TESTES DE ROBUSTEZ")
print("=" * 80)
total = len(test_results)
passed = sum(1 for _, res, _ in test_results if res == "PASS")
failed = total - passed

print(f"Total executados: {total}")
print(f"Passaram:         {passed}")
print(f"Falharam:         {failed}")
print(f"Taxa de sucesso:  {passed / total * 100:.0f}%")
print()

for name, status, detail in test_results:
    symbol = "[OK]" if status == "PASS" else "[XX]"
    print(f"  {symbol} {name}")
    if status == "FAIL":
        print(f"       -> Erro: {detail}")

print("=" * 80)
