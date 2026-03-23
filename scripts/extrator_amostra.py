from playwright.sync_api import sync_playwright
import json
import time

results = {}

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def handle_response(response):
            if "web-bff" in response.url and "PETR26" in response.url and response.request.method == "GET":
                try:
                    data = response.json()
                    name = response.url.split("/")[-1].split("?")[0]
                    if name not in results:
                        results[name] = data
                        print(f"Interceptado JSON da aba: {name}")
                except Exception as e:
                    pass

        page.on("response", handle_response)
        
        urls = [
            "https://data.anbima.com.br/debentures/PETR26/caracteristicas",
            "https://data.anbima.com.br/debentures/PETR26/agenda",
            "https://data.anbima.com.br/debentures/PETR26/precos"
        ]
        
        for u in urls:
            print(f"Acessando {u}...")
            page.goto(u, wait_until="networkidle", timeout=60000)
            time.sleep(3)
            
        with open("amostras_anbima.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
            
        browser.close()

if __name__ == "__main__":
    run()
