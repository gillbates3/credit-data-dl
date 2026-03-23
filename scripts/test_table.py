import json
from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def handle_route(route):
            url = route.request.url
            if "precos/pu-historico" in url and "page=" in url:
                import re
                new_url = re.sub(r"size=\d+", "size=5000", url)
                route.continue_(url=new_url)
            else:
                route.continue_()
                
        page.route("**/*", handle_route)

        def handle_response(response):
            if "precos/pu-historico" in response.url and "page=" in response.url:
                with open("test_table_out.json", "w") as f:
                    json.dump(response.json(), f, indent=2)
                
        page.on("response", handle_response)
        try:
            page.goto("https://data.anbima.com.br/debentures/PETR26/precos", wait_until="networkidle", timeout=10000)
        except: pass
        browser.close()

if __name__ == "__main__":
    run()
