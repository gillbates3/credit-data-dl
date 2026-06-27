"""
Script: servico_identidade.py
Descrição: Serviço assíncrono para identificação de emissores e resolução de cadastros contábeis (CVM).
           Obtém o CNPJ de um ticker de debênture via ANBIMA e localiza o registro CVM usando cache em RAM
           e suporte a arquivos de overrides manuais (overrides_cvm.json).

Funções/Procedimentos:
- normaliza_cnpj(cnpj: str) -> str: Remove pontuação e retorna apenas caracteres numéricos de CNPJ.
- carregar_overrides() -> dict: Lê do arquivo `overrides_cvm.json` mapeamentos de códigos CVM forçados por CNPJ.
- obter_cadastro_cvm() -> list[dict]: Baixa assincronamente a base cadastral de companhias da CVM ou lê do cache de RAM (TTL 24h).
- resolver_cvm(cadastro: list[dict], cnpj: str) -> dict | None: Resolve o cadastro CVM associado a um CNPJ aplicando regras de desempate e prioridade de overrides.
- buscar_identidade_emissor(ticker: str) -> dict: Função principal que busca CNPJ na ANBIMA e o associa com informações da CVM.
"""

import asyncio
import json
import io
import csv
import re
import time
from pathlib import Path
from typing import Callable
import httpx
from playwright.async_api import async_playwright

SCRIPT_DIR = Path(__file__).parent
OVERRIDES_FILE = SCRIPT_DIR / "overrides_cvm.json"
CVM_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"

# In-Memory Cache (Opção A)
_CVM_CACHE = []
_CVM_CACHE_TS = 0
CACHE_TTL = 86400  # 24 horas


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

def normaliza_cnpj(cnpj: str) -> str:
    """Remove pontuações e retorna apenas os números do CNPJ."""
    if not cnpj: return ""
    return re.sub(r"\D", "", str(cnpj))

def carregar_overrides() -> dict:
    """Carrega as correções manuais de código CVM para evitar erros de consistência da CVM."""
    if OVERRIDES_FILE.exists():
        try:
            with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Erro ao ler overrides_cvm.json: {e}")
            return {}
    return {}

async def obter_cadastro_cvm(
    status_callback: Callable[[str], None] | None = None,
) -> list[dict]:
    """Baixa o cadastro completo da CVM ou retorna do In-Memory Cache."""
    global _CVM_CACHE, _CVM_CACHE_TS
    agora = time.time()
    
    # Retorna do cache se existir e tiver menos de 24h
    if _CVM_CACHE and (agora - _CVM_CACHE_TS) < CACHE_TTL:
        _emit_status("Cadastro CVM em cache. Reutilizando base de companhias.", status_callback)
        return _CVM_CACHE
        
    print("[+] Cache CVM vazio ou expirado. Baixando da fonte (~3MB)...")
    _emit_status("Cache CVM vazio ou expirado. Baixando base de companhias...", status_callback)
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(CVM_URL)
        resp.raise_for_status()
        
        # O arquivo da CVM vem em latin-1
        texto = resp.content.decode('latin-1')
        linhas = list(csv.DictReader(io.StringIO(texto), delimiter=";"))
        
        # Atualiza o cache global
        _CVM_CACHE = linhas
        _CVM_CACHE_TS = agora
        print(f"[+] Download CVM concluído e carregado em RAM ({len(linhas)} registros).")
        _emit_status(
            f"Base CVM carregada em memoria com {len(linhas)} registros.",
            status_callback,
        )
        return _CVM_CACHE

def resolver_cvm(cadastro: list[dict], cnpj: str) -> dict | None:
    """Encontra o registro correto na CVM para um dado CNPJ."""
    cnpj_alvo = normaliza_cnpj(cnpj)
    
    # 1. Verifica Overrides Manuais PRIMEIRO
    overrides = carregar_overrides()
    if cnpj_alvo in overrides:
        codigo_override = str(overrides[cnpj_alvo])
        print(f"    [*] OVERRIDE DETECTADO: Usando Código CVM {codigo_override} para o CNPJ {cnpj_alvo}.")
        # Busca o registro na CVM que bata com esse código (para ter a categoria completa)
        for linha in cadastro:
            if str(linha.get("CD_CVM", "")).strip() == codigo_override:
                return linha
        # Se por acaso o código de override não existir no CSV, cria um "fictício"
        return {"CD_CVM": codigo_override, "CATEG_REG": "FORCED_OVERRIDE"}
    
    # 2. Busca convencional no CSV
    candidatos = []
    for linha in cadastro:
        if normaliza_cnpj(linha.get("CNPJ_CIA", "")) == cnpj_alvo:
            candidatos.append(linha)
            
    if not candidatos:
        return None
        
    # Se só achou um, retorna direto
    if len(candidatos) == 1:
        return candidatos[0]
    
    # 3. Inteligência de Desempate (Múltiplos registros para o mesmo CNPJ)
    # Prioriza SIT == "FASE OPERACIONAL" ou SIT_REG == "ATIVO"
    for c in candidatos:
        sit = str(c.get("SIT", "")).upper()
        sit_reg = str(c.get("SIT_REG", "")).upper()
        
        # Algumas empresas ativas estão como OPERACIONAL, outras tem SIT_REG ATIVO
        if "OPERACIONAL" in sit or "ATIVO" in sit_reg:
            return c
            
    # Fallback: retorna o primeiro se não conseguir desempatar inteligentemente
    return candidatos[0]

async def buscar_identidade_emissor(
    ticker: str,
    status_callback: Callable[[str], None] | None = None,
) -> dict:
    """
    Função principal e idempotente do Módulo de Identidade.
    Extrai o CNPJ da ANBIMA e cruza com a CVM na memória RAM.
    """
    ticker_clean = ticker.upper().strip()
    identidade = {
        "ticker": ticker_clean,
        "nome_emissor": None,
        "cnpj_emissor": None,
        "cod_cvm": None,
        "categoria_cvm": None,
        "tipo_capital": "Fechado",
        "status": "ERRO" # Usado para saber se a busca completou com sucesso
    }
    
    print(f"[{ticker_clean}] Buscando características na ANBIMA...")
    _emit_status(
        f"Consultando ANBIMA para identificar o emissor do ticker {ticker_clean}...",
        status_callback,
    )
    # 1. Busca ANBIMA (Playwright Headless)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        
        # Otimização de carga (bloquear imagens e mídia)
        await page.route("**/*.{png,jpg,jpeg,webp,svg,gif}", lambda route: route.abort())
        
        dados_anbima = None
        
        async def handle_response(response):
            nonlocal dados_anbima
            if "web-bff" in response.url and "caracteristicas" in response.url and response.request.method == "GET":
                try:
                    data = await response.json()
                    # Garante que não é um payload vazio de erro de token
                    if data and "emissao" in data:
                        dados_anbima = data
                except:
                    pass

        page.on("response", handle_response)
        
        url_anbima = f"https://data.anbima.com.br/debentures/{ticker_clean}/caracteristicas"
        try:
            await page.goto(url_anbima, wait_until="domcontentloaded", timeout=10000)
            # Wait dynamically until dados_anbima is populated or 5 seconds pass
            for _ in range(50):
                if dados_anbima: break
                await asyncio.sleep(0.1)
        except Exception as e:
            pass
            
        await context.close()
        await browser.close()
        
    if dados_anbima:
        emissor = dados_anbima.get("emissao", {}).get("emissor", {})
        identidade["nome_emissor"] = emissor.get("nome", "").strip()
        identidade["cnpj_emissor"] = normaliza_cnpj(emissor.get("cnpj", ""))
        
    if not identidade["cnpj_emissor"]:
        identidade["status"] = "ERRO_ANBIMA_SEM_CNPJ"
        _emit_status(
            f"A ANBIMA nao retornou CNPJ para o ticker {ticker_clean}.",
            status_callback,
        )
        return identidade
        
    # 2. Busca CVM (In-Memory Cache)
    print(f"[{ticker_clean}] CNPJ encontrado: {identidade['cnpj_emissor']}. Resolvendo CVM...")
    _emit_status(
        f"CNPJ identificado: {identidade['cnpj_emissor']}. Resolvendo cadastro CVM...",
        status_callback,
    )
    cadastro_cvm = await obter_cadastro_cvm(status_callback=status_callback)
    cvm_record = resolver_cvm(cadastro_cvm, identidade["cnpj_emissor"])
    
    if cvm_record:
        cod = str(cvm_record.get("CD_CVM", "")).strip()
        cat = str(cvm_record.get("CATEG_REG", "")).strip()
        
        identidade["cod_cvm"] = cod if cod else None
        identidade["categoria_cvm"] = cat if cat else None
        
        # Correção de Capital Fechado para registros cancelados
        sit = str(cvm_record.get("SIT", "")).upper()
        if "CANCELAD" in sit:
            identidade["tipo_capital"] = "Fechado"
        else:
            identidade["tipo_capital"] = "Aberto"
        _emit_status(
            f"Cadastro CVM localizado para {ticker_clean}: codigo {identidade['cod_cvm'] or 'n/d'}.",
            status_callback,
        )
    else:
        _emit_status(
            f"Nenhum cadastro CVM encontrado para o CNPJ {identidade['cnpj_emissor']}.",
            status_callback,
        )
        
    identidade["status"] = "SUCESSO"
    _emit_status(
        f"Identidade do emissor {ticker_clean} concluida.",
        status_callback,
    )
    return identidade


# ── Execução de Teste Local (Debug) ──────────────────────────────────────────

if __name__ == "__main__":
    import sys
    
    async def debug_run():
        ticker_teste = "PETR26"
        if len(sys.argv) > 1:
            ticker_teste = sys.argv[1].upper()
            
        print("=" * 60)
        print(f" TESTE MÓDULO DE IDENTIDADE V2: {ticker_teste}")
        print("=" * 60)
        
        # Teste 1: Primeira Execução (Baixando CSV)
        start_time = time.time()
        res1 = await buscar_identidade_emissor(ticker_teste)
        tempo1 = time.time() - start_time
        
        # Teste 2: Segunda Execução (Usando Cache de RAM)
        print("\n" + "-" * 60)
        print(" Testando performance da segunda chamada seguida (Cache)...")
        start_time2 = time.time()
        res2 = await buscar_identidade_emissor(ticker_teste)
        tempo2 = time.time() - start_time2
        
        print("\n" + "=" * 60)
        print(f" RESULTADO FINAL")
        print("=" * 60)
        print(json.dumps(res1, indent=2, ensure_ascii=False))
        print(f"\n[Tempo T1 (Sem Cache)] : {tempo1:.2f}s")
        print(f"[Tempo T2 (Com Cache)] : {tempo2:.2f}s")
        
        with open("debug_identidade.json", "w", encoding="utf-8") as f:
            json.dump(res1, f, ensure_ascii=False, indent=2)
            
        print("\n=> Salvo em 'debug_identidade.json' para inspeção.")

    asyncio.run(debug_run())
