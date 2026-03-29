"""
03_download_anbima.py

Baixa dados completos de debêntures através de Web Scraping Dinâmico na plataforma ANBIMA.
Intercepta as respostas do Backend-For-Frontend (BFF) usando Playwright.

Extrai:
 - caracteristicas.json
 - agenda.json
 - historico_diario.json
"""

import json
import traceback
import sys
import csv
from pathlib import Path
from playwright.sync_api import sync_playwright

# ── Configuração ─────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
LANDING_ANBIMA = PROJETO_RAIZ / "data" / "01_landing" / "anbima"

def carregar_tickers() -> list[str]:
    csv_path = PROJETO_RAIZ / "emissoes.csv"
    tickers = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["ticker"]:
                tickers.append(row["ticker"].strip())
    return tickers

TICKERS = carregar_tickers()

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

def f(v) -> float | None:
    if v is None or v == "": return None
    try: return float(str(v).replace(",", "."))
    except (ValueError, TypeError): return None

def i(v) -> int | None:
    if v is None or v == "": return None
    try: return int(float(str(v)))
    except (ValueError, TypeError): return None

def data_curta(v) -> str | None:
    if not v: return None
    return str(v)[:10]

def consolidar_historico(ticker: str, grafico: dict, curva: dict, precos: dict) -> list[dict]:
    por_data = {}
    def base(data: str):
        return {
            "data_referencia": data,
            "pu_par": None, "vna": None, "juros": None, "prazo_remanescente": None,
            "pu_indicativo": None, "taxa_indicativa": None, "taxa_compra": None,
            "taxa_venda": None, "duration_dias_uteis": None, "desvio_padrao": None,
            "percentual_pu_par": None, "percentual_vne": None, "intervalo_indicativo_min": None,
            "intervalo_indicativo_max": None, "referencia_ntnb": None, "spread_indicativo": None,
            "volume_financeiro": None, "quantidade_negocios": None, "quantidade_titulos": None,
            "taxa_media_negocios": None, "pu_medio_negocios": None, "reune": None,
            "percentual_reune": None, "pu_indicativo_status": None, "taxa_indicativa_status": None,
            "flag_status": None, "data_ultima_atualizacao": None
        }

    if grafico and isinstance(grafico, dict):
        for p in grafico.get("pus", []):
            d = p.get("data")
            if d:
                r = por_data.setdefault(d, base(d))
                r["pu_par"] = f(p.get("valor_pu_historico"))
                r["pu_indicativo"] = f(p.get("valor_pu_indicativo"))

    if curva and isinstance(curva, dict):
        for p in curva.get("content", []):
            d = p.get("data_referencia")
            if d:
                r = por_data.setdefault(d, base(d))
                if r["pu_par"] is None: r["pu_par"] = f(p.get("pu_par"))
                r["vna"] = f(p.get("vna"))
                r["juros"] = f(p.get("juros"))
                r["prazo_remanescente"] = i(p.get("prazo_remanescente"))
                r["flag_status"] = p.get("flag_status")
                r["data_ultima_atualizacao"] = data_curta(p.get("data_ultima_atualizacao"))

    if precos and isinstance(precos, dict):
        for p in precos.get("precos", []):
            d = p.get("data_referencia")
            if d:
                r = por_data.setdefault(d, base(d))
                r["taxa_indicativa"] = f(p.get("taxa_indicativa"))
                r["taxa_compra"] = f(p.get("taxa_compra"))
                r["taxa_venda"] = f(p.get("taxa_venda"))
                r["duration_dias_uteis"] = f(p.get("duration"))
                r["percentual_pu_par"] = f(p.get("percentual_pu_par"))
                r["percentual_vne"] = f(p.get("percentual_vne"))
                r["desvio_padrao"] = f(p.get("desvio_padrao"))
                r["reune"] = p.get("reune")
                r["intervalo_indicativo_min"] = f(p.get("intervalo_indicativo_minimo"))
                r["intervalo_indicativo_max"] = f(p.get("intervalo_indicativo_maximo"))
                r["referencia_ntnb"] = p.get("data_referencia_ntnb")
                r["pu_indicativo_status"] = p.get("pu_indicativo_status")
                r["taxa_indicativa_status"] = p.get("taxa_indicativa_status")
                r["percentual_reune"] = f(p.get("percentual_reune"))
                if r["data_ultima_atualizacao"] is None:
                    r["data_ultima_atualizacao"] = data_curta(p.get("data_ultima_atualizacao"))
                if r["pu_indicativo"] is None:
                    r["pu_indicativo"] = f(p.get("pu_indicativo"))

        ph = precos.get("pu_historico", {})
        dt_ph = ph.get("data_referencia")
        if dt_ph:
            r = por_data.setdefault(dt_ph, base(dt_ph))
            if r["pu_par"] is None: r["pu_par"] = f(ph.get("pu_par"))
            if r["vna"] is None: r["vna"] = f(ph.get("vna"))
            if r["juros"] is None: r["juros"] = f(ph.get("juros"))
            if r["prazo_remanescente"] is None: r["prazo_remanescente"] = i(ph.get("prazo_remanescente"))

    return list(por_data.values())

def extrair_ticker(page, ticker: str, destino: Path) -> list[str]:
    """Navega pelo site interceptando as chaves JSON."""
    encontrados = set()
    dados_capturados = {}
    
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
                    dados_capturados[arquivo_nome] = data
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
    
    # Consolidação e salvamento único
    arquivos_finais = []
    if "caracteristicas.json" in dados_capturados:
        salvar_json(dados_capturados["caracteristicas.json"], destino / "caracteristicas.json")
        arquivos_finais.append("caracteristicas.json")
    if "agenda.json" in dados_capturados:
        salvar_json(dados_capturados["agenda.json"], destino / "agenda.json")
        arquivos_finais.append("agenda.json")
        
    historico = consolidar_historico(
        ticker,
        dados_capturados.get("grafico_pu.json"),
        dados_capturados.get("pu_historico.json"),
        dados_capturados.get("precos.json")
    )
    if historico:
        salvar_json(historico, destino / "historico_diario.json")
        arquivos_finais.append("historico_diario.json")
        
    return arquivos_finais

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
    print("Próximo passo: Rodar o script `02_descobrir_emissores.py`")

if __name__ == "__main__":
    main()
