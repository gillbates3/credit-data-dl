import json
from playwright.sync_api import sync_playwright

def run():
    urls = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def handle_response(response):
            if "api.prd.anbima.com.br" in response.url:
                urls.append(response.url)

        page.on("response", handle_response)
        page.goto("https://data.anbima.com.br/debentures/PETR26/precos", wait_until="networkidle")
        page.wait_for_timeout(3000)
        browser.close()
        
    with open("urls_precos.json", "w") as f:
        json.dump(urls, f, indent=2)

if __name__ == "__main__":
    run()
