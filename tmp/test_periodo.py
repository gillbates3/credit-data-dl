from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Intercept route and modify the URL for 'grafico-pu-historico-indicativo'
        def handle_route(route):
            url = route.request.url
            if "grafico-pu-historico-indicativo" in url and "periodo=" in url:
                # Force maximum history (periodo=0)
                import re
                new_url = re.sub(r"periodo=\d+", "periodo=0", url)
                print(f"Modificando URL de {url} para {new_url}")
                route.continue_(url=new_url)
            else:
                route.continue_()
                
        page.route("**/*", handle_route)

        def handle_response(response):
            if "grafico-pu-historico-indicativo" in response.url:
                data = response.json()
                print("PERIODO RECEBIDO:", data.get("periodo"))
                print("TAMANHO DO ARRAY PUS:", len(data.get("pus", [])))
                
        page.on("response", handle_response)
        page.goto("https://data.anbima.com.br/debentures/PETR26/precos", wait_until="networkidle")
        browser.close()

if __name__ == "__main__":
    run()
