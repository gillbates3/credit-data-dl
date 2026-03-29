"""
01_download_anbima.py (Async + Deep Layer)

Baixa dados completos de debêntures através de Web Scraping Dinâmico na plataforma ANBIMA.
Suporta:
 - Camada Light: Cadastro, Agenda, Histórico PU (Gráfico) e Taxas (últimos 5 dias).
 - Camada Deep: Preenchimento de taxas históricas faltantes via Calculadora (UI Interativa).
"""

import json
import asyncio
import csv
import sys
import os
import time
import re
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

# ── Configuração ─────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
LANDING_ANBIMA = PROJETO_RAIZ / "data" / "01_landing" / "anbima"
MAX_CONCURRENT_TICKERS = 3 # Reduzido para evitar bloqueios de IP na calculadora
TICKERS = [] # Variável global que pode ser sobreposta por scripts de teste

def carregar_tickers() -> list[str]:
    csv_path = PROJETO_RAIZ / "emissoes.csv"
    tickers = []
    if not csv_path.exists(): return []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("ticker"):
                tickers.append(row["ticker"].strip())
    return tickers

def salvar_json(dados: dict | list, caminho: Path):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

def resolver_nome_arquivo(url_name: str, ticker: str) -> str:
    if url_name == ticker or url_name == "caracteristicas":
        return "caracteristicas.json"
    elif url_name == "agenda":
        return "agenda.json"
    elif url_name == "pu-historico":
        return "pu_historico.json"
    elif url_name == "grafico-pu-historico-indicativo":
        return "grafico_pu.json"
    return f"{url_name}.json"

# ── Helpers de Conversão ─────────────────────────────────────────────────────

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

# ── Lógica de Consolidação de Histórico ─────────────────────────────────────

def consolidar_historico_light(ticker: str, grafico: dict, curva: dict, precos: dict) -> list[dict]:
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

# ── Extrator Principal ───────────────────────────────────────────────────────

async def extrair_ticker_light(page, ticker: str, destino: Path) -> list[str]:
    carac_path = destino / "caracteristicas.json"
    agenda_path = destino / "agenda.json"
    hist_path = destino / "historico_diario.json"
    
    precisa_carac = not carac_path.exists()
    
    precisa_agenda = True
    if agenda_path.exists():
        if (time.time() - os.path.getmtime(agenda_path)) < 86400: # 24h
            precisa_agenda = False
            
    precisa_hist = True
    if hist_path.exists():
        try:
            with open(hist_path, encoding="utf-8") as f_in:
                existente = json.load(f_in)
                if existente:
                    datas = [r["data_referencia"] for r in existente if r.get("data_referencia")]
                    if datas:
                        ultima = max(datas)
                        hoje = datetime.now().strftime("%Y-%m-%d")
                        ontem = (datetime.now().fromtimestamp(time.time() - 86400)).strftime("%Y-%m-%d")
                        if ultima >= hoje or ultima >= ontem:
                            # Se temos dado recente de PU, talvez não precisemos do gráfico pesado
                            precisa_hist = False
        except: pass

    if not precisa_carac and not precisa_agenda and not precisa_hist:
        return ["SKIP"]

    encontrados = set()
    dados_capturados = {}
    
    async def handle_response(response):
        if "web-bff" in response.url and ticker in response.url and response.request.method == "GET":
            try:
                data = await response.json()
                if not data or ("msg" in data and "token" in str(data.get("msg", "")).lower()):
                    return
                url_name = response.url.split("/")[-1].split("?")[0]
                arquivo_nome = resolver_nome_arquivo(url_name, ticker)
                if arquivo_nome not in encontrados:
                    dados_capturados[arquivo_nome] = data
                    encontrados.add(arquivo_nome)
            except: pass

    # Interceptador para estender o período do gráfico
    async def handle_route(route):
        url = route.request.url
        new_url = re.sub(r"periodo=\d+", "periodo=0", url)
        await route.continue_(url=new_url)

    await page.route("**/grafico-pu-historico-indicativo*", handle_route)
    page.on("response", handle_response)
    
    abas = []
    if precisa_carac: abas.append("caracteristicas")
    if precisa_agenda: abas.append("agenda")
    if precisa_hist: abas.append("precos")
    
    for aba in abas:
        try:
            await page.goto(f"https://data.anbima.com.br/debentures/{ticker}/{aba}", wait_until="networkidle", timeout=45000)
            await asyncio.sleep(2)
        except Exception: pass
            
    page.remove_listener("response", handle_response)
    
    arquivos_finais = []
    if "caracteristicas.json" in dados_capturados:
        salvar_json(dados_capturados["caracteristicas.json"], carac_path)
        arquivos_finais.append("caracteristicas.json")
        
    if "agenda.json" in dados_capturados:
        salvar_json(dados_capturados["agenda.json"], agenda_path)
        arquivos_finais.append("agenda.json")
        
    if precisa_hist or "precos.json" in dados_capturados:
        novo_hist = consolidar_historico_light(
            ticker,
            dados_capturados.get("grafico_pu.json"),
            dados_capturados.get("pu_historico.json"),
            dados_capturados.get("precos.json")
        )
        if novo_hist:
            if hist_path.exists():
                try:
                    with open(hist_path, encoding="utf-8") as f_in:
                        antigo = json.load(f_in)
                        mapa = {r["data_referencia"]: r for r in antigo}
                        for r in novo_hist:
                            # Se já existe no histórico antigo, preserva a taxa indicativa que a Camada Deep suou para pegar
                            if r["data_referencia"] in mapa:
                                old_taxa = mapa[r["data_referencia"]].get("taxa_indicativa")
                                if old_taxa is not None and r.get("taxa_indicativa") is None:
                                    r["taxa_indicativa"] = old_taxa
                            mapa[r["data_referencia"]] = r
                        novo_hist = sorted(mapa.values(), key=lambda x: x["data_referencia"])
                except: pass
            salvar_json(novo_hist, hist_path)
            arquivos_finais.append("historico_diario.json")
        
    return arquivos_finais

# ── Camada Deep (Calculadora) ────────────────────────────────────────────────

async def extrair_taxas_faltantes_calculadora(page, ticker: str, destino: Path):
    hist_path = destino / "historico_diario.json"
    if not hist_path.exists(): return
    
    with open(hist_path, "r", encoding="utf-8") as f:
        historico_diario = json.load(f)

    # Identificar datas sem taxa (excluindo fins de semana/feriados onde PU Par é null talvez? 
    # Melhor pegar tudo que tem PU indicativo mas não tem taxa)
    datas_para_raspar = [
        r["data_referencia"] for r in historico_diario 
        if r.get("taxa_indicativa") is None and r.get("pu_indicativo") is not None
    ]
    
    if not datas_para_raspar:
        return

    print(f" -> [{ticker}] {len(datas_para_raspar)} taxas faltantes...")
    url_calc = f"https://data.anbima.com.br/ferramentas/calculadora/debentures/{ticker}?ativo=debentures"
    
    resultados_taxas = {}
    
    async def handle_response(response):
        if "web-bff" in response.url and "taxas" in response.url:
            try:
                data = await response.json()
                # Extrair ref_date da URL: ...data_referencia=2024-03-24
                match = re.search(r"data_referencia=(\d{4}-\d{2}-\d{2})", response.url)
                if match:
                    ref_date = match.group(1)
                    if "taxa_anbima" in data:
                        resultados_taxas[ref_date] = data["taxa_anbima"]
            except: pass

    page.on("response", handle_response)
    
    try:
        await page.goto(url_calc, wait_until="domcontentloaded", timeout=40000)
        await asyncio.sleep(5)
    except: pass

    # Seletor do input de data (Ajustado para maior robustez)
    date_input_selector = "xpath=//div[contains(text(), 'Data da operação')]/..//input | //label[contains(text(), 'Data da operação')]/..//input"
    loader_selector = "._container_188l7_1" # Seletor do spinner de carregamento observado

    try:
        # Espera o loader sumir se ele aparecer
        if await page.is_visible(loader_selector):
            await page.wait_for_selector(loader_selector, state="hidden", timeout=20000)
        
        # Garante que o input está visível antes de começar
        await page.wait_for_selector(date_input_selector, timeout=15000)
    except:
        # Segundo fallback com seletor de classe parcial
        date_input_selector = "input[class*='_input_']"
        try: 
            await page.wait_for_selector(date_input_selector, timeout=5000)
        except: 
            print(f" -> [{ticker}] ERRO: Não encontrou seletor de data na calculadora.")
            return

    # Iterar nas datas faltantes (do mais recente para o mais antigo)
    datas_para_raspar.sort(reverse=True)
    
    # Remover limite para permitir a varredura até 100% histórico do ticker
    lote = datas_para_raspar
    total_faltantes = len(lote)
    
    falhas_consecutivas = 0
    salvamentos_pendentes = 0
    vagas_preenchidas = 0
    
    for idx, dt_str in enumerate(lote):
        try:
            dt_obj = datetime.strptime(dt_str, "%Y-%m-%d")
            dt_str_input = dt_obj.strftime("%d%m%Y")
            
            input_el = page.locator(date_input_selector).first
            await input_el.click()
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.type(dt_str_input)
            await page.keyboard.press("Enter")
            
            # Pequeno delay para o BFF responder
            await asyncio.sleep(1.2)
            
            taxa_val = resultados_taxas.get(dt_str, 'N/A')
            print(f"[{ticker}] Progresso: {idx + 1}/{total_faltantes} | Data: {dt_str} | Taxa: {taxa_val}")
            
            if taxa_val == 'N/A':
                falhas_consecutivas += 1
            else:
                falhas_consecutivas = 0
                vagas_preenchidas += 1
                
                # Injetar no historico em memoria
                for r in historico_diario:
                    if r["data_referencia"] == dt_str:
                        if isinstance(taxa_val, str):
                            taxa_val = float(taxa_val.replace(",", "."))
                        r["taxa_indicativa"] = taxa_val
                        break
                        
                salvamentos_pendentes += 1
                
            # Checkpoint automático a cada 50 taxas injetadas
            if salvamentos_pendentes >= 50:
                salvar_json(historico_diario, hist_path)
                print(f"[*] [{ticker}] Checkpoint: 50 novas taxas salvas com sucesso.")
                salvamentos_pendentes = 0
                
            if falhas_consecutivas >= 10:
                print(f"[!] [{ticker}] Circuit breaker acionado: 10 falhas seguidas na data. Interrompendo ticker.")
                break
                
        except Exception as e:
            print(f"[{ticker}] Progresso: {idx + 1}/{total_faltantes} | Data: {dt_str} | Erro: {e}")

    page.remove_listener("response", handle_response)
    
    # Salvar o residual do checkpoint
    if salvamentos_pendentes > 0:
        salvar_json(historico_diario, hist_path)
        
    if vagas_preenchidas > 0:
        print(f" -> [{ticker}] OK: Resumo -> {vagas_preenchidas} taxas processadas e injetadas no total.")

# ── Executor de Concorrência ─────────────────────────────────────────────────

async def processar_ticker(browser, ticker: str, semaphore: asyncio.Semaphore):
    async with semaphore:
        destino = LANDING_ANBIMA / ticker
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        
        # Otimização de carga (bloquear mídia)
        await page.route("**/*.{png,jpg,jpeg,webp,svg,gif}", lambda route: route.abort())
        
        try:
            # 1. Camada Light
            print(f"[*] {ticker} Iniciando Camada Light...")
            arquivos = await extrair_ticker_light(page, ticker, destino)
            
            if arquivos == ["SKIP"]:
                print(f"[#] {ticker} Light: Atualizado.")
            elif arquivos:
                print(f"[+] {ticker} Light: OK ({', '.join(arquivos)})")
            
            # 2. Camada Deep (Calculadora)
            # Sempre tentamos preencher se houver lacunas
            await extrair_taxas_faltantes_calculadora(page, ticker, destino)
            
        except Exception as e:
            print(f"[!] {ticker} FALHA: {str(e)[:100]}")
        finally:
            await context.close()

async def main():
    print("\n" + "=" * 60)
    print("  BOCAINA CAPITAL — Download ANBIMA (Async Deep Scraper)")
    print("=" * 60)

    global TICKERS
    args = sys.argv[1:]
    
    if args:
        tickers = [t.upper() for t in args]
    else:
        tickers = TICKERS if TICKERS else carregar_tickers()
        
    if not tickers:
        print("Nenhum ticker fornecido ou encontrado em emissoes.csv")
        return

    print(f"Processando {len(tickers)} tickers com concorrência {MAX_CONCURRENT_TICKERS}...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_TICKERS)
        
        tasks = [processar_ticker(browser, ticker, semaphore) for ticker in tickers]
        await asyncio.gather(*tasks)
        
        await browser.close()

    print("\n" + "-" * 60)
    print("Scraping concluído.")
    print("Próximo passo: Rodar o script `06_parser_silver_anbima.py` para consolidar na Silver.")

if __name__ == "__main__":
    asyncio.run(main())
