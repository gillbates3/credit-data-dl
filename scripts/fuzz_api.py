import time
from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto("https://data.anbima.com.br/debentures/PETR26/precos", wait_until="networkidle")
        time.sleep(2)
        
        endpoints_to_test = [
            "precos/pu-indicativo",
            "precos/pu-indicativo?page=0&size=20",
            "pu-indicativo",
            "pu-indicativo?page=0&size=20",
            "grafico-pu-indicativo?periodo=0"
        ]
        
        for ep in endpoints_to_test:
            script = f'''
            async () => {{
                try {{
                    let r = await fetch("https://data-api.prd.anbima.com.br/web-bff/v1/debentures/PETR26/{ep}");
                    return await r.json();
                }} catch (e) {{
                    return null;
                }}
            }}
            '''
            print(f"Testando: {ep}")
            data = page.evaluate(script)
            if data and "timestamp" not in data and "error" not in data:
                # Se não retornar um objeto de erro gigante do Spring/Java
                keys = list(data.keys()) if isinstance(data, dict) else "array"
                print(f"SUCESSO em {ep}! Chaves/Tipo: {keys}")
                # Imprimir conteúdo se for array ou tiver content
                if isinstance(data, dict) and "content" in data:
                    print("Exemplo:", data["content"][0] if data["content"] else "vazio")
            else:
                print("FALHOU ou retornou erro da API.")
                
        browser.close()

if __name__ == "__main__":
    run()
