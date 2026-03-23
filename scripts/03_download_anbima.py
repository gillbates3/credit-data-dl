"""
03_download_anbima.py

Baixa dados completos de debêntures através de Web Scraping Dinâmico na plataforma ANBIMA.
Intercepta as respostas do Backend-For-Frontend (BFF) usando Playwright.

Extrai:
 - caracteristicas.json
 - agenda.json
 - pu_historico.json
 - grafico_pu.json
"""

import json
import traceback
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

# ── Configuração ─────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
LANDING_ANBIMA = PROJETO_RAIZ / "data" / "01_landing" / "anbima"

TICKERS = [
    # Empresas abertas
    "ALAR14", "CONX12", "CASN34", "CASN24", "ERDVC4", "ENAT33", "IGSS11", "IGSS21",
    "IVIAA0", "AEGE17", "AEGPB5", "RSAN26",
    # Empresas fechadas
    "BTEL13", "BTEL33", "CLTM14", "COMR15", "HGLB13", "HGLB23", "HVSP11", "IRJS15",
    "ISPE12", "ORIG12", "QMCT14", "RALM11", "RGRA11", "RIS422", "RISP22", "RMSA12",
    "SABP12", "SGAB11", "SVEA16", "UNEG11", "CJEN13", "BRKP28", "SCPT13", "CCIA23",
]

def salvar_json(dados: dict | list, caminho: Path):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

def resolver_nome_arquivo(url_name: str, ticker: str) -> str:
    """Mapeia o endpoint do BFF para o nome esperado pelo parser."""
    if url_name == ticker or url_name == "caracteristicas":
        return "caracteristicas.json"
    elif url_name == "agenda":
        return "agenda.json"
    elif url_name == "pu-historico":
        return "pu_historico.json"
    elif url_name == "grafico-pu-historico-indicativo":
        return "grafico_pu.json"
    return f"{url_name}.json"

def extrair_ticker(page, ticker: str, destino: Path) -> list[str]:
    """Navega pelo site interceptando as chaves JSON."""
    encontrados = set()
    
    def handle_response(response):
        if "web-bff" in response.url and ticker in response.url and response.request.method == "GET":
            try:
                data = response.json()
                if not data or ("msg" in data and "token" in str(data.get("msg", "")).lower()):
                    return # Ignora timeouts de token
                
                # Extrair o nome do endpoint
                url_name = response.url.split("/")[-1].split("?")[0]
                arquivo_nome = resolver_nome_arquivo(url_name, ticker)
                
                if arquivo_nome not in encontrados:
                    salvar_json(data, destino / arquivo_nome)
                    encontrados.add(arquivo_nome)
            except Exception:
                pass

    def handle_route(route):
        import re
        url = route.request.url
        new_url = re.sub(r"periodo=\d+", "periodo=0", url)
        route.continue_(url=new_url)

    page.route("**/grafico-pu-historico-indicativo*", handle_route)
    page.on("response", handle_response)
    
    abas = [
        "caracteristicas",
        "agenda",
        "precos"
    ]
    
    for aba in abas:
        sys.stdout.write(f".")
        sys.stdout.flush()
        try:
            # Aumentado o timeout para compensar o carregamento completo do SPA da Anbima
            page.goto(f"https://data.anbima.com.br/debentures/{ticker}/{aba}", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)
        except Exception:
            # Ignora timeouts em abas vazias pra continuar a raspagem
            pass
            
    page.remove_listener("response", handle_response)
    return list(encontrados)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("  BOCAINA CAPITAL — Download ANBIMA (BFF Web Scraping)")
    print("=" * 60)

    sucessos = 0
    erros = 0

    with sync_playwright() as p:
        print("\nIniciando navegador Chromium...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        
        # O interceptador de imagens foi mantido, mas remover as fontes e CSS foi letal para o React.
        page.route("**/*.{png,jpg,jpeg,webp,svg,gif}", lambda route: route.abort())

        for idx, ticker in enumerate(TICKERS, 1):
            print(f"[{idx:02d}/{len(TICKERS)}] {ticker} ", end="")
            destino = LANDING_ANBIMA / ticker
            
            try:
                arquivos = extrair_ticker(page, ticker, destino)
                if arquivos:
                    print(f" OK ({', '.join(arquivos)})")
                    sucessos += 1
                else:
                    print(" NENHUM DADO")
                    erros += 1
            except Exception as e:
                print(f" ERRO: {str(e)[:50]}")
                erros += 1

        browser.close()

    print("\n" + "-" * 60)
    print(f"Downloads concluídos: {sucessos} com dados, {erros} vazios/com erro.")
    print("Próximo passo: Rodar o script `04b_parser_anbima.py`")

if __name__ == "__main__":
    main()
