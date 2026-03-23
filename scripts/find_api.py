from playwright.sync_api import sync_playwright
import time

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        def handle_request(request):
            if "anbima.com.br" in request.url and "titulos" not in request.url and "titulos-privados" not in request.url and "strapi" not in request.url:
                print("API CALL:", request.method, request.url)
        
        page.on("request", handle_request)
        print("Acessando página...")
        page.goto("https://data.anbima.com.br/debentures/ALAR14/agenda", wait_until="networkidle", timeout=60000)
        time.sleep(3) # Aguardar carregamento dos componentes react
        browser.close()
        print("Concluído.")

if __name__ == "__main__":
    run()
