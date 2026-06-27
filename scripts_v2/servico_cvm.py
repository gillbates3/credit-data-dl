"""
Script: servico_cvm.py
Descrição: Serviço modular e assíncrono para consulta e filtragem de demonstrações financeiras (DFP/ITR)
           da base de dados abertos da CVM, com cacheamento de arquivos ZIP em memória para performance.

Funções/Procedimentos:
- normaliza_cod(cod: str) -> str: Normaliza o código CVM removendo zeros à esquerda se numérico.
- normaliza_cnpj(cnpj: str) -> str: Remove caracteres não numéricos do CNPJ.
- nivel_conta(cd_conta: str) -> int: Determina a profundidade hierárquica de uma conta contábil CVM.
- parse_valor(valor_str: str) -> float | None: Converte strings no formato monetário BR para float.
- baixar_zip_cvm(url: str) -> bytes | None: Realiza o download assíncrono do arquivo ZIP da CVM usando cache em memória (TTL 24h).
- extrair_csv_filtrado(zip_bytes: bytes, tabela: str, cod_cvm_alvo: str) -> list[dict]: Extrai e filtra um CSV específico de dentro do ZIP carregado.
- processar_linhas(linhas: list[dict]) -> dict[str, dict]: Processa e formata as contas contábeis de interesse agrupadas por data de referência.
- buscar_dados_cvm(cnpj: str, codigo_cvm: str, anos_retroativos: int = 2) -> dict: Função principal assíncrona para buscar todas as demonstrações CVM no histórico de anos desejado.
"""

import asyncio
import csv
import io
import json
import re
import zipfile
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable
import httpx

SCRIPT_DIR = Path(__file__).parent
DEBUG_FILE = SCRIPT_DIR / "debug_cvm.json"

NIVEL_MAX = 3

BASE_URL = {
    "dfp": "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/",
    "itr": "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/",
}

TABELAS_DFP_ITR = [
    "BPA",
    "BPP",
    "DRE",
    "DFC_MD",
    "DFC_MI",
    "DVA",
]

TABELA_PARA_CHAVE = {
    "BPA": "BPA",
    "BPP": "BPP",
    "DRE": "DRE",
    "DFC_MD": "DFC",
    "DFC_MI": "DFC",
    "DVA": "DVA",
}

# In-Memory Cache (URL -> (bytes, timestamp))
_CVM_CACHE = {}
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

def normaliza_cod(cod: str) -> str:
    s = cod.strip()
    return str(int(s)) if s.isdigit() else s

def normaliza_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", str(cnpj))

def nivel_conta(cd_conta: str) -> int:
    return len(cd_conta.strip().split("."))

def parse_valor(valor_str: str) -> float | None:
    if valor_str is None: return None
    v = str(valor_str).strip().replace(".", "").replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None

async def baixar_zip_cvm(
    url: str,
    status_callback: Callable[[str], None] | None = None,
) -> bytes | None:
    """Baixa um ZIP da CVM usando cache em memória."""
    global _CVM_CACHE
    agora = time.time()
    
    if url in _CVM_CACHE:
        dados, ts = _CVM_CACHE[url]
        if (agora - ts) < CACHE_TTL:
            _emit_status(
                f"Arquivo CVM em cache: {url.split('/')[-1]}",
                status_callback,
            )
            return dados
            
    print(f"    [+] Baixando: {url.split('/')[-1]} (~15-20MB)...")
    _emit_status(
        f"Baixando arquivo da CVM: {url.split('/')[-1]}",
        status_callback,
    )
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code == 404:
                _emit_status(
                    f"Arquivo da CVM indisponivel para {url.split('/')[-1]}.",
                    status_callback,
                )
                return None
            resp.raise_for_status()
            
            conteudo = resp.content
            _CVM_CACHE[url] = (conteudo, agora)
            return conteudo
    except Exception as e:
        print(f"    [!] Erro ao baixar {url}: {e}")
        _emit_status(
            f"Falha ao baixar {url.split('/')[-1]} da CVM.",
            status_callback,
        )
        return None

def extrair_csv_filtrado(zip_bytes: bytes, tabela: str, cod_cvm_alvo: str) -> list[dict]:
    """Extrai e filtra o CSV do ZIP em memória."""
    cod_alvo_norm = normaliza_cod(cod_cvm_alvo)
    linhas_filtradas = []
    
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            nomes_zip = zf.namelist()
            substrings_con = [f"_{tabela}_con_", f"_{tabela.lower()}_con_"]
            substrings_ind = [f"_{tabela}_ind_", f"_{tabela.lower()}_ind_"]
            
            encontrados_con = [n for n in nomes_zip if any(s in n for s in substrings_con)]
            encontrados_ind = [n for n in nomes_zip if any(s in n for s in substrings_ind)]
            
            encontrados = encontrados_con or encontrados_ind
            if not encontrados:
                return []
                
            arquivo_zip = encontrados[0]
            with zf.open(arquivo_zip) as f:
                # Dados da CVM normalmente estão em latin-1
                conteudo_csv = f.read().decode("latin-1")
                
            reader = csv.DictReader(io.StringIO(conteudo_csv), delimiter=";")
            for linha in reader:
                if normaliza_cod(linha.get("CD_CVM", "")) == cod_alvo_norm:
                    linhas_filtradas.append(linha)
                    
            return linhas_filtradas
    except Exception as e:
        print(f"    [!] Erro ao processar tabela {tabela} no ZIP: {e}")
        return []

def processar_linhas(linhas: list[dict]) -> dict[str, dict]:
    """Agrupa linhas por período e conta."""
    por_periodo: dict[str, dict] = defaultdict(dict)
    
    for linha in linhas:
        cd_conta = linha.get("CD_CONTA", "").strip()
        if not cd_conta: continue
            
        if nivel_conta(cd_conta) > NIVEL_MAX:
            continue
            
        dt_refer = linha.get("DT_REFER", "").strip()
        ds_conta = linha.get("DS_CONTA", "").strip()
        vl_conta_str = linha.get("VL_CONTA", "").strip()
        ordem_str = linha.get("ORDEM_EXERC", "").strip()
        
        valor = parse_valor(vl_conta_str)
        if valor is None: continue
            
        # Pula comparativo
        if ordem_str and "LTIMO" in ordem_str.upper() and "PEN" in ordem_str.upper():
            continue
            
        por_periodo[dt_refer][cd_conta] = {
            "cd_conta": cd_conta,
            "ds_conta": ds_conta,
            "valor": valor,
        }
        
    return por_periodo

async def buscar_dados_cvm(
    cnpj: str,
    codigo_cvm: str,
    anos_retroativos: int = 2,
    status_callback: Callable[[str], None] | None = None,
) -> dict:
    """Busca dados contábeis (ITR/DFP) para um CNPJ e código CVM na base de dados abertos."""
    cnpj_norm = normaliza_cnpj(cnpj)
    cod_norm = normaliza_cod(codigo_cvm)
    
    ano_atual = datetime.now().year
    anos = list(range(ano_atual - anos_retroativos, ano_atual + 1))
    
    resultado = {
        "cnpj": cnpj_norm,
        "cod_cvm": cod_norm,
        "periodos": {}
    }
    _emit_status(
        f"Consultando demonstracoes da CVM para o codigo {cod_norm}...",
        status_callback,
    )
    
    dados: dict[str, dict] = defaultdict(lambda: {"tipo": None, "demonstracoes": {}})
    
    # Busca por anos e tipos (DFP depois ITR para o mesmo ano, ou vice-versa)
    # A DFP anual tem precedência, mas o ITR trimestral pode ser mais recente no ano corrente
    for ano in sorted(anos, reverse=True):
        for tipo in ["itr", "dfp"]: # Tenta ITR e DFP
            nome_zip = f"{tipo}_cia_aberta_{ano}.zip"
            url = BASE_URL[tipo] + nome_zip
            
            zip_bytes = await baixar_zip_cvm(url, status_callback=status_callback)
            if not zip_bytes:
                continue
                
            print(f"    [*] Extraindo CSVs ({tipo.upper()} {ano}) para CVM {cod_norm}...")
            _emit_status(
                f"Extraindo demonstracoes {tipo.upper()} de {ano} para o codigo CVM {cod_norm}...",
                status_callback,
            )
            
            for tabela in TABELAS_DFP_ITR:
                chave_dem = TABELA_PARA_CHAVE.get(tabela)
                if not chave_dem: continue
                    
                linhas = extrair_csv_filtrado(zip_bytes, tabela, cod_norm)
                if not linhas:
                    continue
                    
                por_periodo = processar_linhas(linhas)
                for periodo, contas in por_periodo.items():
                    if not contas: continue
                        
                    tipo_upper = tipo.upper()
                    
                    # Evitar sobrescrever DFP com ITR se o ITR do mesmo período for encontrado
                    # Normalmente DFP fecha em 31/12 e ITR até 30/09
                    if periodo not in dados:
                        dados[periodo]["tipo"] = tipo_upper
                        
                    dem = dados[periodo]["demonstracoes"]
                    
                    # DFC: só registra se ainda não tem (MD tem prioridade sobre MI)
                    if chave_dem == "DFC" and "DFC" in dem:
                        continue
                        
                    dem[chave_dem] = contas
                    
    # Ordena os períodos do mais recente para o mais antigo
    for periodo in sorted(dados.keys(), reverse=True):
        resultado["periodos"][periodo] = dict(dados[periodo])
    _emit_status(
        f"Consulta CVM concluida com {len(resultado['periodos'])} periodos encontrados.",
        status_callback,
    )
        
    return resultado

if __name__ == "__main__":
    import sys
    from servico_identidade import buscar_identidade_emissor
    
    async def debug_run():
        ticker_teste = "PETR26"
        if len(sys.argv) > 1:
            ticker_teste = sys.argv[1].upper()
            
        print("=" * 60)
        print(f" TESTE MÓDULO DE BALANÇOS CVM (V2) ")
        print("=" * 60)
        print(f"Descobrindo CNPJ e CVM para: {ticker_teste}...\n")
        
        # Chama o serviço de identidade para descobrir quem é a empresa
        identidade = await buscar_identidade_emissor(ticker_teste)
        
        cnpj_teste = identidade.get("cnpj_emissor")
        cvm_teste = identidade.get("cod_cvm")
        
        if not cnpj_teste or not cvm_teste:
            print(f"[!] Não foi possível encontrar CNPJ/CVM para o ticker {ticker_teste}.")
            print(f"Retorno da Identidade: {identidade}")
            return
            
        print(f"[+] Resolvido -> CNPJ: {cnpj_teste} | CVM: {cvm_teste}")
        print(f"Buscando dados contábeis...\n")
        
        start_time = time.time()
        dados_empresa = await buscar_dados_cvm(cnpj_teste, cvm_teste, anos_retroativos=2)
        tempo = time.time() - start_time
        
        periodos_encontrados = list(dados_empresa.get("periodos", {}).keys())
        print(f"\n[+] Períodos encontrados: {len(periodos_encontrados)}")
        for p in periodos_encontrados:
            tipo = dados_empresa["periodos"][p]["tipo"]
            print(f"    - {p} ({tipo})")
            
        print(f"\nTempo total: {tempo:.2f}s")
        
        with open(DEBUG_FILE, "w", encoding="utf-8") as f:
            json.dump(dados_empresa, f, ensure_ascii=False, indent=2)
            
        print(f"=> Resultados salvos em {DEBUG_FILE.name}")
        
    asyncio.run(debug_run())
