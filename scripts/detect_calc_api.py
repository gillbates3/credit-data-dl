
import json
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

def detect_api():
    ticker = "PETR26"
    url = f"https://data.anbima.com.br/ferramentas/calculadora/debentures/{ticker}?ativo=debentures"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        responses = []
        
        def handle_response(response):
            if "web-bff" in response.url:
                try:
                    # Somente logs de JSON
                    if "json" in response.headers.get("content-type", ""):
                        content = response.json()
                        responses.append({
                            "url": response.url,
                            "method": response.request.method,
                            "status": response.status,
                            "data": content
                        })
                except Exception:
                    pass

        page.on("response", handle_response)
        
        print(f"Navegando para {url}...")
        page.goto(url, wait_until="networkidle")
        
        # Esperar carregar componentes
        time.sleep(3)
        
        print("Limpando capturas iniciais...")
        responses.clear()
        
        # Mudar a data
        # O campo de data geralmente é um input. Vamos tentar localizar por placeholder ou label
        # Baseado no subagent anterior: X:198, Y:589
        print("Alterando a data para 09/12/2025...")
        
        # Tenta focar no input de data
        # No site da Anbima, o campo de data de cálculo costuma ter um seletor específico
        # Vou usar um seletor mais genérico ou clicar na posição conhecida
        page.click("input[placeholder*='Data'], input[aria-label*='Data'], .anbima-ui-input-container input")
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.keyboard.type("09122025")
        page.keyboard.press("Enter")
        
        time.sleep(3)
        
        print(f"Capturadas {len(responses)} respostas após mudança de data.")
        
        for i, resp in enumerate(responses):
            print(f"\n--- Resposta {i+1} ---")
            print(f"URL: {resp['url']}")
            # Salvar amostra
            with open(f"calc_api_resp_{i}.json", "w", encoding="utf-8") as f:
                json.dump(resp['data'], f, indent=2, ensure_ascii=False)

        browser.close()

if __name__ == "__main__":
    detect_api()
