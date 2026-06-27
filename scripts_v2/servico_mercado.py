"""
Script: servico_mercado.py
Descrição: Serviço assíncrono para extração de dados de mercado (características, agenda e preços históricos)
           de debêntures na ANBIMA via Playwright. Suporta a Camada Light (BFF da plataforma) e a Camada Deep
           (preenchimento de taxas pela calculadora da ANBIMA com limitadores e circuit breaker).

Funções/Procedimentos:
- f(v) -> Optional[float]: Converte strings numéricas brasileiras para tipo float.
- i(v) -> Optional[int]: Converte strings/floats numéricos para tipo inteiro.
- data_curta(v) -> Optional[str]: Extrai a substring YYYY-MM-DD de uma data completa.
- parse_remuneracao(remun_str: str, indexador_obj: Any) -> tuple[Optional[str], Optional[float]]: Extrai o indexador e a taxa prefixada da string de remuneração.
- consolidar_historico_light(ticker: str, grafico: dict, curva: dict, precos: dict) -> List[Dict[str, Any]]: Consolida dados diários de PU e taxas da ANBIMA por data.
- extrair_taxas_faltantes_calculadora(page, ticker: str, historico: List[Dict], data_corte_deep: Optional[str] = None, datas_desconhecidas: Optional[List[str]] = None): Busca taxas diárias nulas utilizando a calculadora dinâmica da ANBIMA.
- buscar_dados_mercado(ticker: str, deep: bool = False, data_corte_deep: Optional[str] = None, datas_desconhecidas: Optional[List[str]] = None) -> Dict[str, Any]: Ponto de entrada assíncrono para extração, orquestração e normalização dos dados do ticker.
"""

import json
import asyncio
import re
import sys
import time
from datetime import datetime
from typing import Callable, Dict, List, Any, Optional
from playwright.async_api import async_playwright

# =====================================================================
# FUNÇÕES DE CONVERSÃO E LIMPEZA
# =====================================================================

def _emit_status(
    mensagem: str,
    status_callback: Callable[[str], None] | None = None,
) -> None:
    if not status_callback:
        return
    try:
        status_callback(" ".join(str(mensagem or "").split()))
    except Exception:
        pass

def f(v) -> Optional[float]:
    if v is None or v == "": return None
    try: return float(str(v).replace(",", "."))
    except (ValueError, TypeError): return None

def i(v) -> Optional[int]:
    if v is None or v == "": return None
    try: return int(float(str(v)))
    except (ValueError, TypeError): return None

def data_curta(v) -> Optional[str]:
    if not v: return None
    return str(v)[:10]

def parse_remuneracao(remun_str: str, indexador_obj: Any) -> tuple[Optional[str], Optional[float]]:
    """Extrai o indexador exato e a taxa prefixada de uma string de remuneração."""
    indexador_nome = indexador_obj.get("nome") if isinstance(indexador_obj, dict) else str(indexador_obj) if indexador_obj else None
    taxa_pre = None
    
    if not remun_str:
        return indexador_nome, taxa_pre

    if not indexador_nome or indexador_nome == "None":
        # Tenta extrair "IPCA + 5,5%" ou "100% do CDI"
        match = re.search(r"(\w+)\s*\+\s*([\d\.,]+)%", remun_str)
        if match:
            indexador_nome = match.group(1).strip().upper()
            taxa_pre = f(match.group(2))
        else:
            match_cdi = re.search(r"([\d\.,]+)%\s*do\s*(\w+)", remun_str, re.IGNORECASE)
            if match_cdi:
                indexador_nome = match_cdi.group(2).strip().upper()
                taxa_pre = f(match_cdi.group(1))

    return indexador_nome, taxa_pre

# =====================================================================
# CONSOLIDADOR DO HISTÓRICO
# =====================================================================

def consolidar_historico_light(ticker: str, grafico: dict, curva: dict, precos: dict) -> List[Dict[str, Any]]:
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

    return sorted(list(por_data.values()), key=lambda x: x["data_referencia"])


# =====================================================================
# EXTRATOR DE TAXAS (CAMADA DEEP)
# =====================================================================

async def extrair_taxas_faltantes_calculadora(
    page,
    ticker: str,
    historico: List[Dict],
    data_corte_deep: Optional[str] = None,
    datas_desconhecidas: Optional[List[str]] = None,
    status_callback: Callable[[str], None] | None = None,
):
    # Identificar datas sem taxa indicativa mas com PU indicativo
    datas_para_raspar = [
        r["data_referencia"] for r in historico 
        if r.get("taxa_indicativa") is None and r.get("pu_indicativo") is not None
    ]
    
    if data_corte_deep:
        datas_para_raspar = [d for d in datas_para_raspar if d >= data_corte_deep]
        
    if datas_desconhecidas is not None:
        desconhecidas_set = set(datas_desconhecidas)
        datas_para_raspar = [d for d in datas_para_raspar if d in desconhecidas_set]

    if not datas_para_raspar:
        _emit_status(
            f"Nao ha taxas faltantes para complementar na camada deep de {ticker}.",
            status_callback,
        )
        return

    print(f"[{ticker}] DEEP LAYER: Buscando {len(datas_para_raspar)} taxas faltantes na calculadora (corte: {data_corte_deep})...")
    _emit_status(
        f"Camada deep: buscando {len(datas_para_raspar)} taxas faltantes na calculadora...",
        status_callback,
    )
    url_calc = f"https://data.anbima.com.br/ferramentas/calculadora/debentures/{ticker}?ativo=debentures"
    
    resultados_taxas = {}
    
    async def handle_response(response):
        if "web-bff" in response.url and "taxas" in response.url:
            try:
                data = await response.json()
                match = re.search(r"data_referencia=(\d{4}-\d{2}-\d{2})", response.url)
                if match:
                    ref_date = match.group(1)
                    if "taxa_anbima" in data:
                        resultados_taxas[ref_date] = data["taxa_anbima"]
            except: pass

    page.on("response", handle_response)
    
    try:
        await page.goto(url_calc, wait_until="domcontentloaded", timeout=40000)
        await asyncio.sleep(4)
    except: pass

    date_input_selector = "xpath=//div[contains(text(), 'Data da operação')]/..//input | //label[contains(text(), 'Data da operação')]/..//input"
    loader_selector = "._container_188l7_1"

    try:
        if await page.is_visible(loader_selector):
            await page.wait_for_selector(loader_selector, state="hidden", timeout=20000)
        await page.wait_for_selector(date_input_selector, timeout=15000)
    except:
        date_input_selector = "input[class*='_input_']"
        try: 
            await page.wait_for_selector(date_input_selector, timeout=5000)
        except: 
            print(f"[{ticker}] ERRO: Não encontrou seletor de data na calculadora.")
            _emit_status(
                f"Nao foi possivel localizar o campo de data da calculadora para {ticker}.",
                status_callback,
            )
            page.remove_listener("response", handle_response)
            return

    datas_para_raspar.sort(reverse=True)
    falhas_consecutivas = 0
    vagas_preenchidas = 0
    
    for idx, dt_str in enumerate(datas_para_raspar):
        try:
            dt_obj = datetime.strptime(dt_str, "%Y-%m-%d")
            dt_str_input = dt_obj.strftime("%d%m%Y")
            
            input_el = page.locator(date_input_selector).first
            await input_el.click()
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.type(dt_str_input)
            await page.keyboard.press("Enter")
            
            await asyncio.sleep(1.2)
            
            taxa_val = resultados_taxas.get(dt_str, 'N/A')
            
            if taxa_val == 'N/A':
                falhas_consecutivas += 1
            else:
                falhas_consecutivas = 0
                vagas_preenchidas += 1
                _emit_status(
                    f"Camada deep: taxa preenchida para {dt_str}.",
                    status_callback,
                )
                for r in historico:
                    if r["data_referencia"] == dt_str:
                        if isinstance(taxa_val, str):
                            taxa_val = float(taxa_val.replace(",", "."))
                        r["taxa_indicativa"] = taxa_val
                        break
                
            if falhas_consecutivas >= 10:
                print(f"[{ticker}] Circuit breaker acionado na calculadora. Parando o deep scrape.")
                _emit_status(
                    f"Camada deep interrompida apos muitas falhas consecutivas para {ticker}.",
                    status_callback,
                )
                break
                
        except Exception as e:
            print(f"[{ticker}] Erro na calculadora ({dt_str}): {e}")
            _emit_status(
                f"Falha ao consultar a calculadora para a data {dt_str}.",
                status_callback,
            )

    page.remove_listener("response", handle_response)
    print(f"[{ticker}] DEEP LAYER: {vagas_preenchidas} taxas preenchidas com sucesso.")
    _emit_status(
        f"Camada deep concluida com {vagas_preenchidas} taxas preenchidas.",
        status_callback,
    )


# =====================================================================
# SERVIÇO PRINCIPAL
# =====================================================================

async def buscar_dados_mercado(
    ticker: str,
    deep: bool = False,
    data_corte_deep: Optional[str] = None,
    datas_desconhecidas: Optional[List[str]] = None,
    status_callback: Callable[[str], None] | None = None,
) -> Dict[str, Any]:
    """
    Busca os dados de mercado da ANBIMA para um ticker.
    Retorna dicionário limpo e consolidado com características, agenda e histórico.
    """
    encontrados = set()
    dados_brutos = {}
    
    # Acumuladores e controle para paginação da agenda
    agenda_eventos_acumulados = []
    agenda_paginacao = {"total_pages": 1, "current_page": 0}
    
    async def handle_response(response):
        nonlocal agenda_eventos_acumulados, agenda_paginacao
        if "web-bff" in response.url and ticker in response.url and response.request.method == "GET":
            try:
                data = await response.json()
                if not data or ("msg" in data and "token" in str(data.get("msg", "")).lower()):
                    return
                url_name = response.url.split("/")[-1].split("?")[0]
                
                # Resolução de nome para o dicionário interno
                arquivo_nome = f"{url_name}.json"
                if url_name == ticker or url_name == "caracteristicas":
                    arquivo_nome = "caracteristicas.json"
                elif url_name == "grafico-pu-historico-indicativo":
                    arquivo_nome = "grafico_pu.json"
                elif url_name == "pu-historico":
                    arquivo_nome = "pu_historico.json"

                if url_name == "agenda":
                    if isinstance(data, dict) and "content" in data:
                        eventos = data.get("content", [])
                        for ev in eventos:
                            # Evita adicionar duplicados no acumulo local
                            chave_ev = (ev.get("data_evento"), ev.get("evento"), ev.get("data_base"))
                            chaves_acumuladas = {(e.get("data_evento"), e.get("evento"), e.get("data_base")) for e in agenda_eventos_acumulados}
                            if chave_ev not in chaves_acumuladas:
                                agenda_eventos_acumulados.append(ev)
                        agenda_paginacao["total_pages"] = data.get("total_pages", 1)
                        agenda_paginacao["current_page"] = data.get("number", 0)
                        # Salva em dados_brutos com todo o conteúdo acumulado até agora
                        dados_brutos["agenda.json"] = {"content": agenda_eventos_acumulados}
                else:
                    if arquivo_nome not in encontrados:
                        dados_brutos[arquivo_nome] = data
                        encontrados.add(arquivo_nome)
            except: pass

    async def handle_route(route):
        url = route.request.url
        new_url = url
        if "grafico-pu-historico-indicativo" in url:
            new_url = re.sub(r"periodo=\d+", "periodo=0", new_url)
        if "agenda" in url:
            new_url = re.sub(r"size=\d+", "size=100", new_url)
            
        await route.continue_(url=new_url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        
        # Bloquear mídia para otimização
        await page.route("**/*.{png,jpg,jpeg,webp,svg,gif}", lambda route: route.abort())
        await page.route("**/web-bff/**", handle_route)
        page.on("response", handle_response)
        
        print(f"[{ticker}] Navegando para extração de dados brutos (API BFF)...")
        _emit_status(
            f"Abrindo ANBIMA para coletar caracteristicas, agenda e historico de {ticker}...",
            status_callback,
        )
        abas = ["caracteristicas", "agenda", "precos"]
        for aba in abas:
            try:
                print(f"[{ticker}] -> Acessando aba: {aba}")
                _emit_status(
                    f"Lendo aba {aba} da ANBIMA...",
                    status_callback,
                )
                # domcontentloaded evita os timeouts de 30s causados por trackers ou long-polling
                await page.goto(f"https://data.anbima.com.br/debentures/{ticker}/{aba}", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
                
                if aba == "agenda":
                    # Se houver mais páginas da agenda, percorre clicando no botão de paginação
                    await asyncio.sleep(1) # Garante que a primeira resposta foi processada
                    for _ in range(15): # Limite de segurança de 15 páginas
                        if agenda_paginacao["current_page"] + 1 >= agenda_paginacao["total_pages"]:
                            break
                        
                        print(f"[{ticker}] -> Agenda possui mais páginas. Carregando próxima página ({agenda_paginacao['current_page'] + 1} de {agenda_paginacao['total_pages']})...")
                        _emit_status(
                            f"Carregando pagina {agenda_paginacao['current_page'] + 2} de {agenda_paginacao['total_pages']} da agenda...",
                            status_callback,
                        )
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await asyncio.sleep(0.5)
                        
                        next_btn = page.locator("#pagination-next-button")
                        if await next_btn.is_visible() and await next_btn.is_enabled():
                            await next_btn.click()
                            await asyncio.sleep(2) # Espera resposta ser processada
                        else:
                            break
            except Exception as e:
                print(f"[{ticker}] -> Aviso ao acessar aba {aba}: {e}")
                _emit_status(
                    f"Aviso ao acessar a aba {aba} da ANBIMA para {ticker}.",
                    status_callback,
                )
            
        page.remove_listener("response", handle_response)

        print(f"[{ticker}] Consolidando Histórico Diário (Camada Light)...")
        _emit_status(
            f"Consolidando historico diario da camada light para {ticker}...",
            status_callback,
        )
        # 1. Historico (Light + Deep opcional)
        historico_diario = consolidar_historico_light(
            ticker,
            dados_brutos.get("grafico_pu.json"),
            dados_brutos.get("pu_historico.json"),
            dados_brutos.get("precos.json")
        )

        if deep:
            print(f"[{ticker}] Iniciando rotina de Camada Deep (Calculadora)...")
            _emit_status(
                f"Iniciando camada deep da calculadora para complementar taxas de {ticker}...",
                status_callback,
            )
            await extrair_taxas_faltantes_calculadora(
                page,
                ticker,
                historico_diario,
                data_corte_deep,
                datas_desconhecidas,
                status_callback=status_callback,
            )
        else:
            print(f"[{ticker}] Camada Deep desativada. Pulando calculadora.")
            _emit_status(
                f"Camada deep desativada para {ticker}; seguindo apenas com a camada light.",
                status_callback,
            )

        await context.close()
        await browser.close()

    # ==================================================
    # PARSING FINAL (Baseado no 08_upsert_supabase.py)
    # ==================================================
    
    print(f"[{ticker}] Aplicando regras de limpeza e padronização dos dados...")
    _emit_status(
        f"Aplicando limpeza e padronizacao final dos dados de mercado de {ticker}...",
        status_callback,
    )
    # 1. Características
    c_raw = dados_brutos.get("caracteristicas.json", {})
    emissao = c_raw.get("emissao", {}) or {}
    emissor = emissao.get("emissor", {}) or {}
    indexador_obj = c_raw.get("indexador", {}) or {}
    
    indexador_nome, taxa_pre = parse_remuneracao(c_raw.get("remuneracao", ""), indexador_obj)
    
    vol_emissao = f(emissao.get("volume") or c_raw.get("volume"))
    qtd_emissao = i(emissao.get("quantidade_emitida"))
    pu_emissao = (vol_emissao / qtd_emissao) if (vol_emissao and qtd_emissao) else None

    prazo_anos = None
    d_emissao = emissao.get("data_emissao")
    d_vencim = c_raw.get("data_vencimento")
    if d_emissao and d_vencim:
        try:
            dt_e = datetime.strptime(d_emissao, "%Y-%m-%d")
            dt_v = datetime.strptime(d_vencim, "%Y-%m-%d")
            prazo_anos = round((dt_v - dt_e).days / 365.25, 2)
        except: pass

    coord_lider = emissao.get("coordenador_lider", {}) or {}
    agf = emissao.get("agente_fiduciario", {}) or {}

    caracteristicas_limpas = {
        "nome_emissor":            emissor.get("nome"),
        "tipo":                    "debenture",
        "isin":                    c_raw.get("isin"),
        "serie":                   c_raw.get("numero_serie"),
        "numero_emissao":          i(emissao.get("numero_emissao")),
        "data_emissao":            d_emissao,
        "data_vencimento":         d_vencim,
        "prazo_anos":              prazo_anos,
        "volume_emissao":          vol_emissao,
        "valor_unitario_emissao":  pu_emissao,
        "quantidade_debentures":   qtd_emissao,
        "indexador":               indexador_nome,
        "taxa_prefixada":          taxa_pre or f(c_raw.get("taxa_emissao")),
        "especie":                 emissao.get("garantia"),
        "lei_incentivo":           "Sim" if c_raw.get("lei") else "Não",
        "banco_coordenador":       coord_lider.get("nome") or coord_lider.get("razao_social"),
        "agente_fiduciario":       agf.get("nome") or agf.get("razao_social"),
        "banco_liquidante":        emissao.get("banco_mandatario"),
        "status":                  "ativo",
        "dados_anbima":            c_raw
    }

    # 2. Agenda
    agenda_raw = dados_brutos.get("agenda.json", {})
    eventos_raw = agenda_raw.get("content", []) if isinstance(agenda_raw, dict) else agenda_raw
    agenda_limpa = []
    
    for ev in eventos_raw:
        if not ev.get("data_evento"): continue
        agenda_limpa.append({
            "data_evento":     ev.get("data_evento"),
            "data_base":       ev.get("data_base"),
            "data_liquidacao": ev.get("data_liquidacao"),
            "evento":          ev.get("evento"),
            "evento_arc":      ev.get("evento_arc"),
            "taxa":            f(ev.get("taxa")),
            "valor":           f(ev.get("valor")),
            "status":          ev.get("status", {}).get("status") if isinstance(ev.get("status"), dict) else str(ev.get("status")),
            "grupo_status":    ev.get("status", {}).get("grupo_status") if isinstance(ev.get("status"), dict) else None
        })

    _emit_status(
        f"Coleta de mercado concluida: {len(agenda_limpa)} eventos e {len(historico_diario)} dias de historico.",
        status_callback,
    )
    return {
        "ticker_deb": ticker,
        "caracteristicas": caracteristicas_limpas,
        "agenda": agenda_limpa,
        "historico_diario": historico_diario
    }

# =====================================================================
# BLOCO DE TESTE
# =====================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Módulo de Mercado - Extração ANBIMA")
    parser.add_argument("ticker", nargs="?", default="PETR26", help="Ticker da debênture (ex: PETR26)")
    parser.add_argument("--deep", action="store_true", help="Ativa a ida à calculadora para buscar taxas faltantes")
    parser.add_argument("--corte", type=str, default=None, help="Data de corte para a Camada Deep (formato YYYY-MM-DD)")
    args = parser.parse_args()

    ticker_teste = args.ticker.upper()
    print(f"[{ticker_teste}] Testando Serviço de Mercado ANBIMA...")
    print(f"Modo Deep: {args.deep}")
    if args.deep and args.corte:
        print(f"Data Corte Deep: {args.corte}")
    
    inicio = time.time()
    dados = asyncio.run(buscar_dados_mercado(ticker_teste, deep=args.deep, data_corte_deep=args.corte))
    fim = time.time()
    
    print(f"\n[SUCESSO] Extração concluída em {fim - inicio:.2f} segundos")
    print(f"-> Características parseadas: {len(dados['caracteristicas'])} campos")
    print(f"-> Agenda: {len(dados['agenda'])} eventos")
    print(f"-> Histórico Diário: {len(dados['historico_diario'])} dias registrados")
    
    with open("scripts_v2/debug_mercado.json", "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    print("Resultado completo salvo em: scripts_v2/debug_mercado.json")
