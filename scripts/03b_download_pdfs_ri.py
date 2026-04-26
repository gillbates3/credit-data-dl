import argparse
import json
import logging
import os
import re
import math
import hashlib
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from google import genai
from google.genai import types
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Carrega variáveis de ambiente
load_dotenv()

# Configuração de Logger
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configurações globais
CONFIANCA_MINIMA = int(os.environ.get("CONFIANCA_MINIMA", 70))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY não encontrada no .env. A busca automática de URLs pode falhar.")

# Constantes Playwright
MAX_SUBPAGES = 8
BROWSER_TIMEOUT = 15000

# Dicionários de Regras
REGRAS_TIPO_PDF = {
    "DFP": r"(demonstra[çc][õo]es\s+financeiras|dfp|demonstra[çc][õo]es\s+completas|financial\s+statements|balan[çc]o(\s+patrimonial)?)",
    "ITR": r"(itr|trimestral|trimestre|quarterly|[1-4]t)",
    "release": r"(release|resultados|earnings|press\s+release)",
    "relatorio_administracao": r"(relat[óo]rio\s+d[ea]\s+administra[çc][ãa]o|ra)"
}

PALAVRAS_CHAVE_SUBPAGINAS = [
    "demonstracoes", "demonstrações", "financeiras", "resultados",
    "itr", "dfp", "relatorio", "relatório", "administracao", "administração",
    "release", "earnings", "transparencia", "transparência",
    "publicacoes", "publicações", "documentos"
]


def limpa_cnpj(cnpj_str: str) -> str:
    """Remove caracteres não numéricos do CNPJ e completa com zeros a esquerda se necessário."""
    digits = re.sub(r"\D", "", str(cnpj_str))
    return digits.zfill(14)

def sanitize_filename(filename: str) -> str:
    """Sanitiza nomes de arquivos para evitar erros no SO."""
    clean = re.sub(r'[^A-Za-z0-9_.-]', '_', filename)
    return clean[:120]

def descobrir_url_ri(empresa: str, cnpj: str) -> dict:
    """Usa o Gemini com Google Search para encontrar a URL de RI da empresa."""
    if not GEMINI_API_KEY:
         return {"url_ri": "", "confianca": 0, "observacoes": "API KEY não configurada"}

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        prompt = f"""
        Você é um assistente especializado em coleta de dados corporativos no Brasil.
        Sua tarefa é usar a busca na web para encontrar o site EXATO e OFICIAL de Relações com Investidores (RI), Transparência ou Investidores da empresa abaixo:
        
        Nome: {empresa}
        CNPJ: {cnpj}

        REGRAS CRÍTICAS DE ANTI-ALUCINAÇÃO:
        1. Cuidado com homônimos e empresas similares (ex: "Origem" vs "Origem Energia"). Cruze a informação do domínio com o nome completo e a atuação da empresa.
        2. NUNCA retorne portais agregadores de dados financeiros ou de CNPJ (ex: Econodata, CNPJ.biz, CasadosDados, StatusInvest, Fundamentus, InfoMoney). O link DEVE ser o domínio corporativo do próprio emissor.
        3. Se não encontrar o site oficial da própria empresa, retorne "url_ri": "" (vazio) com confianca 0.

        Considere que a empresa pode ser de capital aberto (com site de RI em um subdomínio como ri.empresa.com.br) ou fechado (página de Transparência/Investidores dentro do site principal).

        Retorne exclusivamente um JSON válido, sem texto adicional, sem markdown, e sem blocos de código, no formato exato:
        {{
          "url_ri": "https://...",
          "confianca": 87,
          "observacoes": "Site de RI oficial encontrado no domínio corporativo da empresa"
        }}

        Critério de 'confianca' (inteiro de 0 a 100):
        - 90-100: URL oficial da própria empresa, verificada sem dúvidas batendo nome e segmento, sendo claramente a seção de RI ou Transparência.
        - 70-89: Site institucional oficial correto, mas não encontrou uma página específica de RI visível na busca.
        - 50-69: Domínio parece bater com o nome, mas há divergências fortes ou chance de ser uma empresa homônima.
        - 0-49: Incerteza absoluta, ou só há links de terceiros. (Neste caso prefira retornar string vazia na url com confianca 0).
        """
        
        # Tool de Search
        google_search_tool = types.Tool(
            google_search=types.GoogleSearch()
        )
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[google_search_tool],
                temperature=0.0
            )
        )
        
        res_text = response.text.strip()
        # Limpar crases de markdown caso a LLM desobedeça
        res_text = re.sub(r'^```(json)?|```$', '', res_text).strip()
        
        data = json.loads(res_text)
        return {
            "url_ri": data.get("url_ri", ""),
            "confianca": int(data.get("confianca", 0)),
            "observacoes": data.get("observacoes", "")
        }
    except Exception as e:
        logger.error(f"Erro na LLM para a empresa {empresa}: {e}")
        return {"url_ri": "", "confianca": 0, "observacoes": f"Erro na chamada da LLM: {str(e)}"}

def descobrir_todas_urls(empresas_list: list) -> tuple:
    """Descobre e separa empresas com alta confiança das duvidosas."""
    alta_confianca = []
    pendentes_revisao = []
    
    print("\n" + "="*80)
    print("INICIANDO DESCOBERTA DE URLs COM IA (Camada 1)")
    print("="*80)
    
    for emp in empresas_list:
        nome = emp['nome']
        cnpj = emp['cnpj']
        
        # Otimização 1: bypass de LLM se o metadata.json já possuir a URL de RI salva
        cnpj_num = limpa_cnpj(cnpj)
        meta_file = Path("data/01_landing/manual_uploads") / cnpj_num / "metadata.json"
        
        if meta_file.exists():
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                    if meta.get('url_ri'):
                        print(f"\n➜ [Bypass] Recarregando URL já validada no metadata para: {nome} (CNPJ: {cnpj})...")
                        emp['url_confirmada'] = meta['url_ri']
                        emp['status_empresa'] = meta.get('status_empresa', 'concluido')
                        
                        if emp['status_empresa'] != 'ignorada':
                            alta_confianca.append(emp)
                        else:
                            # Adiciona às pendentes só pra ser logada como ignorada depois, 
                            # ou se for 'ignorada', podemos só colocar no pendentes para cair no if ignorado.
                            pendentes_revisao.append(emp) 
                            
                        continue
            except Exception:
                pass
                
        print(f"\nBusca automática para: {nome} (CNPJ: {cnpj})...")
        llm_result = descobrir_url_ri(nome, cnpj)
        
        url_ri = llm_result['url_ri']
        confianca = llm_result['confianca']
        obs = llm_result['observacoes']
        
        emp['url_encontrada'] = url_ri
        emp['confianca_encontrada'] = confianca
        emp['obs_encontrada'] = obs
        
        # Confirmação automática (ignora o prompt) se a confiança for muito alta
        CONFIANCA_AUTO = 95
        if confianca >= CONFIANCA_AUTO and url_ri:
            print(f"➜ Confirmado automaticamente! ({confianca}/100) -> {url_ri}")
            emp['url_confirmada'] = url_ri
            emp['status_empresa'] = 'concluido'
            alta_confianca.append(emp)
        else:
            print(f"➜ Confiança baixa ({confianca}/100) ou ausente. Separada para revisão manual.")
            pendentes_revisao.append(emp)
            
    return alta_confianca, pendentes_revisao

def revisar_pendentes_terminal(pendentes: list) -> list:
    """Passa pelas empresas pendentes interagindo com o usuário."""
    confirmadas = []
    if not pendentes:
        return confirmadas
        
    print("\n" + "="*80)
    print("REVISÃO MANUAL DE EMPRESAS PENDENTES")
    print("="*80)
    print(f"Temos {len(pendentes)} empresa(s) que precisam de a sua confirmação.")
    
    for emp in pendentes:
        nome = emp['nome']
        cnpj = emp['cnpj']
        url_ri = emp.get('url_encontrada', '')
        confianca = emp.get('confianca_encontrada', 0)
        obs = emp.get('obs_encontrada', '')
        
        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"Empresa         : {nome}")
        print(f"CNPJ            : {cnpj}")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"URL encontrada  : {url_ri}")
        print(f"Confiança       : {confianca}/100")
        print(f"Observações     : {obs}")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        sugestao = "S" if confianca >= CONFIANCA_MINIMA and url_ri else "m"
        escolha_valida = False
        
        while not escolha_valida:
            resp = input(f"Deseja prosseguir com essa URL? [S/n/m (m = inserir manualmente)] (Padrão: {sugestao}): ").strip().lower()
            
            if not resp:
                resp = sugestao.lower()
                
            if resp == 's':
                emp['url_confirmada'] = url_ri
                emp['status_empresa'] = 'concluido'
                confirmadas.append(emp)
                escolha_valida = True
            elif resp == 'n':
                emp['url_confirmada'] = ""
                emp['status_empresa'] = 'ignorada'
                logger.info(f"Empresa {nome} ignorada pelo usuário.")
                confirmadas.append(emp) # Será ignorada depois
                escolha_valida = True
            elif resp == 'm':
                man_url = input("Digite a URL manualmente: ").strip()
                if man_url:
                    emp['url_confirmada'] = man_url
                    emp['status_empresa'] = 'concluido'
                    confirmadas.append(emp)
                    escolha_valida = True
                else:
                    print("URL inválida.")
            else:
                 print("Opção inválida, digite S, n ou m.")
                 
    return confirmadas

def identifica_tipo_e_ano_pdf(texto_ancora: str, href: str) -> tuple:
    """Classifica o tipo do PDF e extrai o ano."""
    texto_combinado = f"{texto_ancora} {href}".lower()
    
    tipo_encontrado = "outros"
    for tipo, regex in REGRAS_TIPO_PDF.items():
        if re.search(regex, texto_combinado):
            tipo_encontrado = tipo
            break
            
    # Extrai o ano
    ano_encontrado = "ano_desconhecido"
    
    # Procura anos explicitos 2021-2025
    match_ano = re.search(r'(202[1-5])', texto_combinado)
    if match_ano:
        ano_encontrado = int(match_ano.group(1))
    else:
        # Tenta achar formato trimestral tipo 1T22, 1T2022
        match_tri = re.search(r'[1-4]t(20)?(2[1-5])', texto_combinado)
        if match_tri:
            ano_abr = match_tri.group(2) # "22" ou "23" etc
            ano_encontrado = int(f"20{ano_abr}")
            
    return tipo_encontrado, ano_encontrado

def load_or_create_metadata(dir_path: Path, cnpj_numeros: str, base_emp: dict) -> dict:
    meta_file = dir_path / "metadata.json"
    if meta_file.exists():
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Erro ao carregar metadata existente: {e}")
            
    return {
        "empresa": base_emp["nome"],
        "cnpj": base_emp["cnpj"],
        "cnpj_numeros": cnpj_numeros,
        "url_ri": base_emp.get("url_confirmada", ""),
        "confianca_url": None,
        "data_execucao": datetime.now().isoformat(),
        "status_empresa": base_emp.get("status_empresa", ""),
        "arquivos": [],
        "erros": []
    }

def save_metadata(dir_path: Path, metadata: dict):
    meta_file = dir_path / "metadata.json"
    with open(meta_file, 'w', encoding='utf-8') as f:
         json.dump(metadata, f, ensure_ascii=False, indent=2)

def navegar_e_extrair_v2(empresa: dict, run_dir: Path) -> dict:
    """Camada 2 - Navegação via Playwright, buscando as subpáginas e listando PDFs."""
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    
    cnpj_num = limpa_cnpj(empresa['cnpj'])
    emp_dir = run_dir / cnpj_num
    emp_dir.mkdir(parents=True, exist_ok=True)
    
    metadata = load_or_create_metadata(emp_dir, cnpj_num, empresa)
    
    if metadata['status_empresa'] in ['ignorada', 'erro_fatal']:
        save_metadata(emp_dir, metadata)
        return metadata

    url = empresa['url_confirmada']
    if not url:
        return metadata
        
    logger.info(f"[{empresa['nome']}] Navegando em: {url}")
    
    pdfs_encontrados = [] # Dicionario com href, anchor, page_url
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            
            try:
                page.goto(url, timeout=BROWSER_TIMEOUT, wait_until="domcontentloaded")
            except PlaywrightTimeoutError:
                logger.warning(f"Timeout ao carregar {url}. Tentando prosseguir...")
            except Exception as e:
                logger.error(f"Erro fatal ao navegar na url principal {url}: {e}")
                metadata['status_empresa'] = 'erro_fatal'
                metadata['erros'].append({"url": url, "motivo": str(e)})
                save_metadata(emp_dir, metadata)
                return metadata
                
            # Extrair subpáginas candidatas da Home
            links = page.locator("a").all()
            candidate_urls = set()
            candidate_urls.add(url) # Adicionar a propria home
            
            base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            
            for lnk in links:
                try:
                    href = lnk.get_attribute("href")
                    texto = lnk.inner_text().strip()
                    if href:
                        href_lower = href.lower()
                        texto_lower = texto.lower()
                        
                        # Se é PDF, guarda direto
                        if href_lower.endswith('.pdf') or 'download' in href_lower:
                            # Guarda pra verificação depois se é link válido
                            pdfs_encontrados.append({
                                'url_pdf': urljoin(base_url, href),
                                'texto': texto,
                                'pagina': url
                            })
                            continue
                            
                        # Verifica se é uma subpágina candidata
                        if any(kw in href_lower or kw in texto_lower for kw in PALAVRAS_CHAVE_SUBPAGINAS):
                            # Evita sair do domínio, a menos que seja um subdomínio
                            full_cand_url = urljoin(base_url, href)
                            if urlparse(full_cand_url).netloc.endswith(urlparse(url).netloc.replace("www.", "")):
                                candidate_urls.add(full_cand_url)
                except Exception:
                    continue
                    
            candidate_urls = list(candidate_urls)[:MAX_SUBPAGES]
            logger.info(f"[{empresa['nome']}] {len(candidate_urls)} páginas candidatas a varrer.")
            
            for idx, sub_url in enumerate(candidate_urls):
                if sub_url == url: continue # Já varriei PDFs na home (vide loop acima, na home eu extraí os <a href>)
                
                logger.info(f"  [{empresa['nome']}] Varrendo subpágina ({idx+1}/{len(candidate_urls)}): {sub_url}")
                try:
                    page.goto(sub_url, timeout=10000, wait_until="domcontentloaded")
                    sub_links = page.locator("a").all()
                    logger.info(f"  [{empresa['nome']}] => Analisando {len(sub_links)} links dessa subpágina...")
                    
                    for lnk in sub_links:
                        try:
                             href = lnk.get_attribute("href")
                             texto = lnk.inner_text().strip()
                             if href:
                                 href_lower = href.lower()
                                 # Simplificando a busca por PDF: Verifica se termina em .pdf ou tem algo evidente de download. 
                                 # A regra estrita é verificar a url_pdf depois no Requests
                                 if href_lower.endswith('.pdf') or 'download' in href_lower:
                                    # Para n pegar urls mt genéricas
                                    url_formatada = urljoin(base_url, href)
                                    pdfs_encontrados.append({
                                        'url_pdf': url_formatada,
                                        'texto': texto,
                                        'pagina': sub_url
                                    })
                        except Exception:
                            continue
                except PlaywrightTimeoutError:
                     logger.warning(f"  Timeout na subpágina {sub_url}")
                except Exception as e:
                     logger.warning(f"  Erro ao acessar subpágina {sub_url}: {e}")
                     
            browser.close()
            
    except Exception as e:
         logger.error(f"Falha severa do Playwright para {empresa['nome']}: {e}")
         # Opcional: Adicionar um fallback usando BeautifulSoup
         fallback_crawl(empresa, url, pdfs_encontrados)
         
    # Processar os PDFs encontrados e baixar
    pdfs_encontrados_unicos = {p['url_pdf']: p for p in pdfs_encontrados}.values()
    
    for pdf_data in pdfs_encontrados_unicos:
        tipo, ano = identifica_tipo_e_ano_pdf(pdf_data['texto'], pdf_data['url_pdf'])
        
        # Ignorar apenas se acharmos que é antes de 2021 explicitamente
        # Porem nossa regex só pegou 2021-2025 ou desconhecido. 
        # Vou pegar tudo o que foi classificado (os "ano_desconhecido" tbm entram)
        match_antigo = re.search(r'(19\d\d|200\d|201\d|2020)', pdf_data['texto'] + pdf_data['url_pdf'])
        if match_antigo and ano == "ano_desconhecido":
            continue # Ignorar antigo explicitamente não pego na regex
            
        realizar_download_pdf(empresa, pdf_data, tipo, ano, emp_dir, metadata)

    save_metadata(emp_dir, metadata)
    return metadata

def fallback_crawl(empresa, base_url, pdfs_encontrados):
    """Fallback usando requisições simples com BeautifulSoup"""
    logger.info(f"Iniciando Fallback com BeautifulSoup para {empresa['nome']}")
    try:
        resp = requests.get(base_url, timeout=30, verify=False)
        soup = BeautifulSoup(resp.content, "lxml")
        
        for a in soup.find_all('a', href=True):
             href = a['href']
             texto = a.get_text(strip=True)
             if href.lower().endswith('.pdf'):
                  pdfs_encontrados.append({
                      'url_pdf': urljoin(base_url, href),
                      'texto': texto,
                      'pagina': base_url
                  })
    except Exception as e:
        logger.error(f"Fallback falhou: {e}")

def realizar_download_pdf(empresa, pdf_data, tipo_doc, ano, out_dir, metadata):
    """Camada 3 - Download e Verificação do PDF via HTTP"""
    url_pdf = pdf_data['url_pdf']
    texto_ancora = pdf_data['texto']
    
    # Valida se já existe
    hash_txt = hashlib.md5(url_pdf.encode('utf-8')).hexdigest()[:8]
    sanitized_txt = sanitize_filename(texto_ancora) if texto_ancora else "pdf"
    nome_arquivo = f"{tipo_doc}_{ano}_{sanitized_txt}_{hash_txt}.pdf"
    
    caminho_arquivo = out_dir / nome_arquivo
    
    # Verifica duplicação no metadata ou no disco
    for arch in metadata['arquivos']:
        if arch['url_origem'] == url_pdf:
             return # Já processado (pode ser repetido no link)
             
    if caminho_arquivo.exists():
         metadata['arquivos'].append({
               "nome_arquivo": nome_arquivo, "tipo": tipo_doc, "ano": ano,
               "url_origem": url_pdf, "pagina_origem": pdf_data['pagina'],
               "download_status": "ja_existente"
         })
         return
         
    # Configura tentativas de download de ate 60s
    attempts = 3
    sucesso = False
    
    for i in range(attempts):
         try:
             # Head para verificar tamanho antes? Evitar +40MB
             r_head = requests.head(url_pdf, timeout=10, allow_redirects=True, verify=False)
             if 'Content-Length' in r_head.headers:
                 tamanho = int(r_head.headers['Content-Length'])
                 if tamanho > 40 * 1024 * 1024:
                      logger.warning(f"  [{empresa['nome']}] PDF maior que 40MB: {url_pdf}")
                      metadata['erros'].append({"url": url_pdf, "motivo": "Excede 40MB"})
                      return
             
             r = requests.get(url_pdf, timeout=60, stream=True, verify=False)
             r.raise_for_status()
             
             # Ler inicio para verificar "%PDF"
             primeiros_bytes = r.iter_content(chunk_size=1024)
             chunk = next(primeiros_bytes, b"")
             if not chunk.startswith(b"%PDF"):
                 logger.warning(f"  [{empresa['nome']}] Arquivo não é PDF válido: {url_pdf}")
                 metadata['erros'].append({"url": url_pdf, "motivo": "Magic byte não é %PDF"})
                 return
                 
             with open(caminho_arquivo, 'wb') as f:
                  f.write(chunk)
                  for rest in r.iter_content(chunk_size=8192):
                      if rest:
                          f.write(rest)
                          
             sucesso = True
             metadata['arquivos'].append({
                   "nome_arquivo": nome_arquivo, "tipo": tipo_doc, "ano": ano,
                   "url_origem": url_pdf, "pagina_origem": pdf_data['pagina'],
                   "tamanho_bytes": caminho_arquivo.stat().st_size,
                   "download_status": "sucesso"
             })
             break
         except Exception as e:
             logger.warning(f"  [{empresa['nome']}] Tentativa {i+1} falhou - {e}. Retrying...")
             import time
             time.sleep(2 ** i)
             
    if not sucesso:
         metadata['erros'].append({"url": url_pdf, "motivo": "Timeout ou falha após 3 tentativas"})


def main():
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    parser = argparse.ArgumentParser(description="Downloader e Descobridor de Módulo de RI")
    parser.add_argument("--csv", default="empresas.csv", help="Caminho do CSV de empresas")
    parser.add_argument("--col-empresa", default="nome", help="Nome da coluna com o nome da empresa")
    parser.add_argument("--col-cnpj", default="cnpj", help="Nome da coluna com o CNPJ")
    args = parser.parse_args()

    # Prepara pasta base
    base_out_dir = Path("data/01_landing/manual_uploads")
    base_out_dir.mkdir(parents=True, exist_ok=True)
    
    # Verifica o CSV
    csv_path = Path(args.csv)
    if not csv_path.exists():
        logger.error(f"Arquivo CSV não encontrado: {csv_path}")
        return
        
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        logger.error(f"Falha ao ler o CSV: {e}")
        return
        
    if args.col_empresa not in df.columns or args.col_cnpj not in df.columns:
        logger.error(f"Colunas {args.col_empresa} e/ou {args.col_cnpj} não existem no CSV. Colunas disponíveis: {df.columns.tolist()}")
        return
        
    # Converter em dict e remover nulos
    empresas_list = []
    for _, row in df.iterrows():
        emp = str(row[args.col_empresa])
        cnp = str(row[args.col_cnpj])
        if emp.strip() and emp != 'nan' and cnp.strip() and cnp != 'nan':
             empresas_list.append({'nome': emp.strip(), 'cnpj': limpa_cnpj(cnp)})
             
    total = len(empresas_list)
    logger.info(f"Total de {total} empresas carregadas do CSV.")
    
    resumo_execucao = {
        "sucesso": 0,
        "ignoradas": 0,
        "erros_fatais": [],
        "arquivos_baixados": 0
    }
    
    # FASE 1: Descobrir URLs via LLM
    alta_confianca, pendentes = descobrir_todas_urls(empresas_list)
    
    # FASE 2: Processar automaticamente empresas de alta confiança
    if alta_confianca:
        print("\n" + "="*80)
        print("CRAWLING E DOWNLOAD (Alta Confiança)")
        print("="*80)
        for emp in alta_confianca:
            res_meta = navegar_e_extrair_v2(emp, base_out_dir)
            if res_meta['status_empresa'] == 'erro_fatal':
                resumo_execucao['erros_fatais'].append(emp['nome'])
            else:
                resumo_execucao['sucesso'] += 1
            resumo_execucao['arquivos_baixados'] += len([x for x in res_meta.get('arquivos', []) if x['download_status'] == 'sucesso'])
            
    # FASE 3: Revisar pendentes com o usuário
    pendentes_revisadas = revisar_pendentes_terminal(pendentes)
    
    # FASE 4: Processar as aprovadas manualmente
    pendentes_aprovadas = [e for e in pendentes_revisadas if e.get('status_empresa') != 'ignorada']
    ignoradas = [e for e in pendentes_revisadas if e.get('status_empresa') == 'ignorada']
    resumo_execucao['ignoradas'] += len(ignoradas)
    
    if pendentes_aprovadas:
        print("\n" + "="*80)
        print("CRAWLING E DOWNLOAD (Aprovadas Manualmente)")
        print("="*80)
        for emp in pendentes_aprovadas:
            res_meta = navegar_e_extrair_v2(emp, base_out_dir)
            if res_meta['status_empresa'] == 'erro_fatal':
                resumo_execucao['erros_fatais'].append(emp['nome'])
            else:
                resumo_execucao['sucesso'] += 1
            resumo_execucao['arquivos_baixados'] += len([x for x in res_meta.get('arquivos', []) if x['download_status'] == 'sucesso'])
            
    print("\n" + "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("RESUMO DA EXECUÇÃO")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Total de empresas no CSV : {total}")
    print(f"Processadas com sucesso  : {resumo_execucao['sucesso']}")
    print(f"Ignoradas pelo usuário   : {resumo_execucao['ignoradas']}")
    print(f"Erros fatais             : {len(resumo_execucao['erros_fatais'])}")
    if resumo_execucao['erros_fatais']:
        print("Empresas com erro fatal  : " + ", ".join(resumo_execucao['erros_fatais']))
    print(f"Total de PDFs baixados   : {resumo_execucao['arquivos_baixados']}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

if __name__ == "__main__":
    main()
