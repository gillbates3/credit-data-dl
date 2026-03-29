
import json
import time
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

def extrair_historico_anbima(ticker="PETR26"):
    landing_path = Path(f"data/01_landing/anbima/{ticker}/historico_diario.json")
    if not landing_path.exists():
        print(f"Erro: {landing_path} não encontrado. Execute o consolidado primeiro.")
        return

    # Carregar o histórico diário existente
    with open(landing_path, "r", encoding="utf-8") as f:
        historico_diario = json.load(f)

    # Identificar datas que precisam de taxa (onde taxa_indicativa é null)
    datas_para_raspar = [r["data_referencia"] for r in historico_diario if r.get("taxa_indicativa") is None]
    
    if not datas_para_raspar:
        print(f"Todas as taxas para {ticker} já estão preenchidas.")
        return

    print(f"Iniciando raspagem de {len(datas_para_raspar)} taxas faltantes para {ticker}...")
    url_calc = f"https://data.anbima.com.br/ferramentas/calculadora/debentures/{ticker}?ativo=debentures"
    
    resultados_taxas = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        # Interceptador para capturar a taxa do BFF
        def handle_response(response):
            if "web-bff" in response.url and "taxas" in response.url:
                try:
                    data = response.json()
                    ref_date = response.url.split("data_referencia=")[-1]
                    if "taxa_anbima" in data:
                        resultados_taxas[ref_date] = data["taxa_anbima"]
                except Exception:
                    pass

        page.on("response", handle_response)
        
        try:
            page.goto(url_calc, wait_until="domcontentloaded", timeout=40000)
            time.sleep(3)
        except Exception:
            pass

        date_input_selector = "xpath=//div[contains(text(), 'Data da operação')]/..//input"
        # Fallback para seletor genérico caso o XPath falhe
        if not page.is_visible(date_input_selector):
            date_input_selector = "_input_1paj3_1" # Seletor específico observado em debug anterior ou similar

        try:
            page.wait_for_selector(date_input_selector, timeout=20000)
        except:
            # Tenta um seletor ainda mais genérico se o anterior falhar
            date_input_selector = "input[placeholder*='Data'], input[class*='_input_']"
            page.wait_for_selector(date_input_selector, timeout=20000)

        # Iterar nas datas faltantes (da mais recente para a mais antiga)
        datas_para_raspar.sort(reverse=True)
        
        total = len(datas_para_raspar)
        for idx, dt_str in enumerate(datas_para_raspar, 1):
            try:
                dt_obj = datetime.strptime(dt_str, "%Y-%m-%d")
                dt_str_input = dt_obj.strftime("%d%m%Y")
                
                input_el = page.locator(date_input_selector).first
                input_el.click()
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.type(dt_str_input)
                page.keyboard.press("Enter")
                
                print(f"Progresso {ticker}: [{idx}/{total}] {dt_str}...", end="\r")
                page.wait_for_timeout(700)
                
            except Exception as e:
                print(f"\nErro na data {dt_str}: {e}")

        browser.close()

    # Injetar taxas coletadas no objeto original
    vagas_preenchidas = 0
    for r in historico_diario:
        dt = r["data_referencia"]
        if dt in resultados_taxas:
            taxa_val = resultados_taxas[dt]
            if isinstance(taxa_val, str):
                taxa_val = float(taxa_val.replace(",", "."))
            r["taxa_indicativa"] = taxa_val
            vagas_preenchidas += 1

    # Salvar de volta no historico_diario.json
    with open(landing_path, "w", encoding="utf-8") as f:
        json.dump(historico_diario, f, indent=2, ensure_ascii=False)

    print(f"\nFinalizado: {vagas_preenchidas} taxas injetadas diretamente em {landing_path}")

if __name__ == "__main__":
    import sys
    ticker_alvo = sys.argv[1] if len(sys.argv) > 1 else "PETR26"
    extrair_historico_anbima(ticker_alvo)
