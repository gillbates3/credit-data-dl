from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def handle_request(request):
            if "grafico-pu-historico-indicativo" in request.url:
                print("HEADERS USADOS:")
                for k, v in request.headers.items():
                    print(f"{k}: {v}")

        page.on("request", handle_request)
        page.goto("https://data.anbima.com.br/debentures/PETR26/precos", wait_until="networkidle")
        browser.close()

if __name__ == "__main__":
    run()
