"""
utils_ri_downloader.py — RI Document Downloader
=============================================
Baixa documentos de sites de Relações com Investidores (plataforma MZ Group / MZiQ).

Estrutura de pastas gerada:
──────────────────────────────────────────────────────
  <pasta-de-saída>/
    <Nome da Aba>/        ← uma pasta por empresa/SPE encontrada
      arquivo1.pdf
      arquivo2.xlsx
      ...
    manifesto.json
    catalogo.json

Exemplos concretos:

  Arteris/
    Arteris/
      2024-03-15_Release Resultados 4T23.pdf
      2024-01-10_Relatorio Agente Fiduciario.pdf
    Intervias/
      2024-03-15_Release Resultados 4T23.pdf
    Via Paulista/
      ...
    Planalto Sul/
      ...

  Igua/
    Grupo Igua/
      2024-11-13_ITR 3T24.pdf
    Igua Rio/
      ...
    Igua Sergipe/
      ...

  Aegea/
    Central De Resultados/
      2024-11-06_Release 3T24.pdf
      ...
──────────────────────────────────────────────────────

Instalação:
    pip install playwright requests tqdm
    playwright install chromium

Uso:
    # Arteris — todas as 8 abas, documentos de 2022 em diante
    python utils_ri_downloader.py \\
        --url https://ri.arteris.com.br/informacoes-aos-investidores/central-de-resultados/arteris/ \\
        --from-year 2022 --out ./Arteris

    # Iguá — todas as abas, 2023+
    python utils_ri_downloader.py \\
        --url https://ri.igua.com.br/informacoes-aos-investidores/central-de-resultados/ \\
        --from-year 2023 --out ./Igua

    # Aegea — 2023+
    python utils_ri_downloader.py \\
        --url https://ri.aegea.com.br/informacoes-aos-investidores/central-de-resultados/ \\
        --from-year 2023 --out ./Aegea

    # Só a aba atual (sem descobrir irmãs)
    python utils_ri_downloader.py \\
        --url https://ri.arteris.com.br/informacoes-aos-investidores/central-de-resultados/intervias/ \\
        --from-year 2023 --no-all-tabs --out ./Arteris

    # Descobrir sem baixar
    python utils_ri_downloader.py \\
        --url https://ri.arteris.com.br/informacoes-aos-investidores/central-de-resultados/arteris/ \\
        --from-year 2023 --discover-only --out ./Arteris
"""

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from tqdm import tqdm

# ──────────────────────────────────────────────────────────────
# CONSTANTES
# ──────────────────────────────────────────────────────────────

FILE_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".zip", ".csv"}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
}

REQUEST_DELAY = 0.4     # segundos entre requests HTTP
MAX_RETRIES   = 3
PLAYWRIGHT_TO = 30_000  # ms

MZIQ_API = "https://api.mziq.com/mzfilemanager/v2/d"

# UUIDs MZiQ já confirmados (usados como cache; detectados automaticamente se ausentes)
KNOWN_UUIDS: dict[str, str] = {
    "ri.igua.com.br":        "3c6adbe6-b0cd-4d47-a8c2-30892fd45b3d",
    "ri.aegea.com.br":       "9aa4d8c5-604a-4097-acc9-2d8be8f71593",
    "ri.ecorodovias.com.br": "7c109ecb-88c9-441f-91cb-66a8db417120",
    "ri.bravaenergia.com":   "55b913af-cd4c-48d5-bc19-48c63916b8a5",
    "ri.vtal.com":           "a379b0ec-46e1-430a-97e4-7b74422808d2",
}

# Categorias de documentos padrão da plataforma MZ
MZ_CATEGORIES = [
    "acordo-de-acionistas", "apresentacao-de-resultados", "assembleias-gerais",
    "codigo-de-etica-e-conduta", "comunicado-ao-mercado",
    "comunicados-e-fatos-relevantes", "demonstracoes-financeiras",
    "documentos-debenture", "edital-de-convocacao", "escritura-de-emissao",
    "estatuto-social", "fatos-relevantes", "formulario-cadastral",
    "formulario-de-referencia", "fundamentos-e-planilhas",
    "informacoes-contabeis-trimestrais", "outros-documentos-cvm",
    "politicas-e-regimentos", "propostas-da-administracao", "ratings",
    "relatorio-anual-do-agente-fiduciario", "relatorios",
    "reunioes-do-conselho-de-administracao", "oferta-publica",
    "apresentacoes", "central-de-resultados",
]


# ──────────────────────────────────────────────────────────────
# UTILITÁRIOS
# ──────────────────────────────────────────────────────────────

def sanitize(name: str, max_len: int = 100) -> str:
    """Remove caracteres inválidos para nomes de arquivo/pasta."""
    name = re.sub(r"<[^>]+>", "", name)                       # strip HTML tags
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name)       # chars inválidos → espaço
    name = re.sub(r"\s+", " ", name).strip()
    return name[:max_len] or "arquivo"


def slug_to_label(slug: str) -> str:
    """Converte um slug de URL em nome de pasta legível.
    Ex: 'regis-bittencourt' → 'Regis Bittencourt'
        'central-de-resultados-igua-rio' → 'Igua Rio'
    """
    # Remove prefixos comuns que não agregam ao nome
    for prefix in ("central-de-resultados-", "central-de-resultados"):
        if slug.startswith(prefix):
            slug = slug[len(prefix):].strip("-") or slug
    label = slug.replace("-", " ").title()
    return sanitize(label) or slug


def is_file_url(url: str) -> bool:
    if "mzfilemanager" in url.lower() or "filemanager-cdn" in url.lower():
        return True
    return Path(urlparse(url).path).suffix.lower() in FILE_EXTENSIONS


def year_from(s: str) -> int | None:
    m = re.search(r"(20\d{2})", s or "")
    return int(m.group(1)) if m else None


def dedupe(links: list[dict]) -> list[dict]:
    seen, out = set(), []
    for l in links:
        if l["url"] not in seen:
            seen.add(l["url"])
            out.append(l)
    return out


def fetch_json(url: str, session: requests.Session, params: dict = None):
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(url, headers=DEFAULT_HEADERS,
                            params=params or {}, timeout=25)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (403, 404):
                return None
            time.sleep(1)
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                print(f"   ⚠ {e} [{url[:80]}]")
            time.sleep(1.5)
    return None


def download_file(url: str, dest: Path, session: requests.Session) -> bool:
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(url, headers={**DEFAULT_HEADERS, "Accept": "*/*"},
                            stream=True, timeout=90)
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f, tqdm(
                total=total, unit="B", unit_scale=True,
                desc=dest.name[:48], leave=False, ncols=88
            ) as bar:
                for chunk in r.iter_content(16_384):
                    f.write(chunk)
                    bar.update(len(chunk))
            return True
        except Exception as e:
            print(f"   ⚠ tentativa {attempt+1}: {e}")
            time.sleep(2)
    return False


# ──────────────────────────────────────────────────────────────
# DETECÇÃO DE UUID MZiQ
# ──────────────────────────────────────────────────────────────

def detect_uuid(url: str, session: requests.Session) -> str | None:
    """
    Retorna o UUID MZiQ da empresa, procurando em:
    1. Cache KNOWN_UUIDS (por hostname)
    2. Regex nos links mzfilemanager do HTML da página
    """
    hostname = urlparse(url).netloc
    if hostname in KNOWN_UUIDS:
        print(f"   UUID (cache): {KNOWN_UUIDS[hostname]}")
        return KNOWN_UUIDS[hostname]
    try:
        r = session.get(url, headers=DEFAULT_HEADERS, timeout=20)
        found = re.findall(
            r"(?:mziq|mzfilemanager)[^\"\'<>]*?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            r.text, re.IGNORECASE
        )
        if found:
            uuid = Counter(found).most_common(1)[0][0]
            print(f"   UUID (detectado no HTML): {uuid}")
            return uuid
    except Exception as e:
        print(f"   ⚠ Erro ao detectar UUID: {e}")
    print("   UUID não encontrado — continuando sem API MZiQ direta.")
    return None


# ──────────────────────────────────────────────────────────────
# DESCOBERTA DE ABAS (URLs irmãs na Central de Resultados)
# ──────────────────────────────────────────────────────────────

def discover_tabs(page_url: str, session: requests.Session) -> list[dict]:
    """
    A partir de uma URL de aba, descobre todas as abas irmãs no mesmo
    nível de path.

    Exemplo: dado /central-de-resultados/arteris/
    descobre:   /central-de-resultados/intervias/
                /central-de-resultados/viapaulista/
                etc.

    Retorna lista de dicts: [{slug, label, url}]
    """
    try:
        r = session.get(page_url, headers=DEFAULT_HEADERS, timeout=20)
    except Exception as e:
        print(f"   ⚠ Erro ao buscar abas: {e}")
        slug = _url_slug(page_url)
        return [{"slug": slug, "label": slug_to_label(slug), "url": page_url}]

    parsed = urlparse(page_url)
    base   = f"{parsed.scheme}://{parsed.netloc}"
    parts  = [p for p in parsed.path.split("/") if p]
    # path-pai = todos os segmentos menos o último
    parent = "/" + "/".join(parts[:-1]) + "/" if len(parts) > 1 else "/"

    current_slug = parts[-1] if parts else "principal"
    seen  = {page_url}
    tabs  = [{"slug": current_slug,
              "label": slug_to_label(current_slug),
              "url": page_url}]

    for href in re.findall(r'href=["\']([^"\'#?]+)["\']', r.text):
        # Normaliza para URL absoluta
        if href.startswith("/"):
            full = base + href
        elif href.startswith("http"):
            full = href
        else:
            continue

        p = urlparse(full)
        if p.netloc != parsed.netloc:
            continue

        # Path normalizado (com trailing slash)
        path = p.path.rstrip("/") + "/"
        if not path.startswith(parent):
            continue

        # Aceita só filhos diretos do pai (um único nível abaixo)
        remainder = path[len(parent):].strip("/")
        if not remainder or "/" in remainder:
            continue

        # Garante que não é a própria página atual
        full_clean = base + path
        if full_clean in seen:
            continue
        seen.add(full_clean)

        tabs.append({
            "slug":  remainder,
            "label": slug_to_label(remainder),
            "url":   full_clean,
        })

    if len(tabs) > 1:
        print(f"   {len(tabs)} abas encontradas:")
        for t in tabs:
            print(f"     • {t['label']:35s}  {t['url']}")
    else:
        print("   Nenhuma aba adicional (página única).")

    return tabs


def _url_slug(url: str) -> str:
    """Extrai o último segmento significativo do path da URL.
    Para URLs raiz (ex: ri.vtal.com/) usa o hostname como slug.
    """
    parts = [p for p in urlparse(url).path.split("/") if p]
    if parts:
        return parts[-1]
    # URL raiz: usa o hostname sem o prefixo ri. ou www.
    hostname = urlparse(url).netloc
    hostname = re.sub(r"^(ri\.|www\.)", "", hostname)   # remove prefixo
    hostname = hostname.split(".")[0]                    # pega só o nome
    return hostname or "principal"


# ──────────────────────────────────────────────────────────────
# CAMADA 1 — API MZiQ DIRETA
# ──────────────────────────────────────────────────────────────

def _mziq_list(uuid: str, session: requests.Session,
               params: dict = None) -> list[dict]:
    data = fetch_json(f"{MZIQ_API}/{uuid}/contents", session, params)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("contents", "results", "files", "items", "data"):
            if k in data and isinstance(data[k], list):
                return data[k]
    return []


def _mziq_to_links(docs: list[dict], uuid: str,
                   from_year: int, to_year: int,
                   tab_label: str) -> list[dict]:
    """
    Converte objetos da API MZiQ em dicts padronizados.

    Filtro de ano: usa APENAS o metadado year/date da API — nunca infere
    ano por nome de arquivo, URL ou texto de link.

    Nome de arquivo: título cadastrado na plataforma, ou UUID como fallback.
    Sem prefixo de data, sem código de categoria.
    """
    links = []
    for doc in docs:
        # Ano confiável: campo year do metadado MZiQ
        yr = doc.get("year")
        if yr is None:
            d = doc.get("date") or doc.get("publishDate") or ""
            if d and len(d) >= 4 and d[:4].isdigit():
                yr = int(d[:4])
        # Aplica filtro — se yr ainda for None, inclui (não descarta por falta de metadado)
        if from_year and yr is not None and yr < from_year:
            continue
        if to_year and yr is not None and yr > to_year:
            continue

        # URL do arquivo (primeiro campo preenchido ganha)
        fid = doc.get("id") or doc.get("fileId") or doc.get("uuid")
        file_url = None
        for field in ("path", "url", "fileUrl", "file_url", "link"):
            v = doc.get(field)
            if v and isinstance(v, str) and v.strip():
                file_url = v if v.startswith("http") else f"{MZIQ_API}/{uuid}/{v}"
                break
        if not file_url:
            for ver in (doc.get("versions") or doc.get("files") or []):
                for field in ("path", "url", "fileUrl"):
                    v = ver.get(field)
                    if v and isinstance(v, str) and v.strip():
                        file_url = v if v.startswith("http") else f"{MZIQ_API}/{uuid}/{v}"
                        break
                if file_url:
                    break
        if not file_url and fid:
            file_url = f"{MZIQ_API}/{uuid}/{fid}?origin=2"
        if not file_url:
            continue

        # Nome do arquivo: título da API, sem nenhum código extra
        raw_title = (doc.get("title") or doc.get("name") or doc.get("filename") or "").strip()
        title = sanitize(raw_title) if raw_title else str(fid or "arquivo")

        ext = Path(urlparse(file_url).path).suffix.lower() or ".pdf"

        links.append({
            "url":   file_url,
            "title": title,
            "tab":   tab_label,
            "year":  yr,
            "ext":   ext,
            "source": "mziq-api",
        })
    return dedupe(links)


def mziq_fetch_tab(uuid: str, session: requests.Session,
                   from_year: int, to_year: int,
                   categories: list[str],
                   tab_label: str) -> list[dict]:
    """
    Busca todos os documentos de uma aba via API MZiQ.
    """
    all_docs = []
    start_yr = from_year if from_year is not None else 2010
    end_yr   = to_year if to_year is not None else 2030
    years    = list(range(start_yr, end_yr + 1))

    # Teste rápido para validar se o endpoint da API é suportado por esta empresa
    test_data = fetch_json(f"{MZIQ_API}/{uuid}/contents", session, {"page": 1, "pageSize": 1})
    if test_data is None:  # None indica falha grave (ex: HTML retornado em vez de JSON ou erro 404/500 contínuo)
        print("     ⚠ API MZiQ não respondeu corretamente. Pulando Camada 1 para esta aba.")
        return []

    print(f"     anos: {years[0]}–{years[-1]}", end="", flush=True)
    for yr in years:
        params = {"year": yr, "lang": "pt-br"}
        if categories:
            for cat in categories:
                docs = _mziq_list(uuid, session, {**params, "category": cat})
                all_docs.extend(docs)
                time.sleep(REQUEST_DELAY)
        else:
            docs = _mziq_list(uuid, session, params)
            all_docs.extend(docs)
            time.sleep(REQUEST_DELAY)
        print(".", end="", flush=True)
    print()

    page_num = 1
    while True:
        docs = _mziq_list(uuid, session,
                          {"lang": "pt-br", "page": page_num, "pageSize": 100})
        if not docs:
            break
        all_docs.extend(docs)
        if len(docs) < 100:
            break
        page_num += 1
        time.sleep(REQUEST_DELAY)

    return _mziq_to_links(dedupe(all_docs), uuid, from_year, to_year, tab_label)


# ──────────────────────────────────────────────────────────────
# CAMADA 2 — PLAYWRIGHT (browser headless + interceptação de rede)
# ──────────────────────────────────────────────────────────────

def playwright_scrape(url: str, from_year: int, to_year: int,
                      tab_label: str) -> tuple[list[dict], list[str]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("   ⚠ Playwright não instalado. "
              "Execute: pip install playwright && playwright install chromium")
        return [], []

    file_links: list[dict] = []
    api_calls:  list[str]  = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page    = browser.new_context(
            user_agent=DEFAULT_HEADERS["User-Agent"], locale="pt-BR"
        ).new_page()

        def on_request(req):
            u = req.url
            if any(p in u for p in ["api.mziq", "wp-json", "mzfilemanager"]):
                api_calls.append(u)
            if is_file_url(u):
                file_links.append({
                    "url":   u,
                    "title": sanitize(Path(urlparse(u).path).stem),
                    "tab":   tab_label,
                    "date":  "",
                    "year":  None,
                    "ext":   Path(urlparse(u).path).suffix.lower(),
                    "source": "playwright-intercept",
                })

        page.on("request", on_request)

        try:
            page.goto(url, wait_until="networkidle", timeout=PLAYWRIGHT_TO)
        except Exception:
            page.goto(url, wait_until="domcontentloaded", timeout=PLAYWRIGHT_TO)
        time.sleep(2)

        _pw_click_years(page, from_year, to_year, file_links, tab_label)
        file_links.extend(_pw_dom_links(page, tab_label))
        
        # Expande todos os accordions e detalhes genéricos
        page.evaluate("""
            document.querySelectorAll('.accordion__item__header, .accordion-title, [class*="accordion"], summary, .dropdown-toggle').forEach(el => {
                try { el.click(); } catch(e) {}
            });
        """)
        
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)
        file_links.extend(_pw_dom_links(page, tab_label))

        browser.close()

    return dedupe(file_links), list(set(api_calls))


def _pw_click_years(page, from_year, to_year, file_links, tab_label):
    """
    Clica em todos os elementos interativos que revelam documentos:
    1. Dropdowns <select> de ano
    2. Botões/links com atributo data-year
    3. Itens de menu de categoria (padrão MZ: li com texto de categoria)
       — necessário para sites como Vtal onde cada categoria do menu
         lateral precisa ser clicada para revelar seus documentos.
    """
    try:
        # 1. Dropdowns <select> de ano
        for sel in page.query_selector_all("select"):
            for opt in sel.query_selector_all("option"):
                val  = opt.get_attribute("value") or ""
                text = opt.inner_text().strip()
                yr   = year_from(val) or year_from(text)
                if yr is None:
                    continue
                if from_year and yr < from_year:
                    continue
                if to_year and yr > to_year:
                    continue
                try:
                    sel.select_option(value=val)
                    page.wait_for_load_state("networkidle", timeout=5_000)
                    time.sleep(1)
                    
                    # Captura o estado do DOM agora que o ano foi selecionado!
                    page.evaluate("""
                        document.querySelectorAll('.accordion__item__header, .accordion-title, [class*="accordion"], summary, .dropdown-toggle').forEach(el => {
                            try { el.click(); } catch(e) {}
                        });
                    """)
                    time.sleep(1)
                    file_links.extend(_pw_dom_links(page, tab_label))
                    
                except Exception:
                    pass

        # 2. Botões/links com data-year explícito
        for btn in page.query_selector_all(
            "button[data-year], a[data-year], li[data-year], "
            "[class*='year'] button, [class*='year'] a, "
            "[class*='ano'] button, [class*='ano'] a"
        ):
            val = btn.get_attribute("data-year") or btn.inner_text().strip()
            yr  = year_from(val)
            if yr is None:
                continue
            if from_year and yr < from_year:
                continue
            if to_year and yr > to_year:
                continue
            try:
                btn.click(timeout=3_000)
                page.wait_for_load_state("networkidle", timeout=5_000)
                time.sleep(1)
                
                # Captura o estado do DOM agora que o ano foi clicado
                page.evaluate("""
                    document.querySelectorAll('.accordion__item__header, .accordion-title, [class*="accordion"], summary, .dropdown-toggle').forEach(el => {
                        try { el.click(); } catch(e) {}
                    });
                """)
                time.sleep(1)
                file_links.extend(_pw_dom_links(page, tab_label))
                
            except Exception:
                pass

        # 3. Menu lateral de categorias MZ (padrão: <li> clicável sem href)
        # Clicar em cada categoria revela os documentos daquela seção.
        # Evitamos clicar em itens que possuem um link <a href="URL"> real, pois
        # geralmente são links para outras abas (o que faria misturar arquivos de concessionárias).
        print("     clicando nas categorias do menu...", flush=True)
        cat_items = page.query_selector_all(
            "nav li, .menu li, [class*='category'] li, "
            "[class*='categoria'] li, aside li, .sidebar li, "
            "ul.categories li, ul.menu-items li"
        )
        clicked = 0
        for item in cat_items:
            text = (item.inner_text() or "").strip()
            if not text or len(text) > 80:
                continue
            
            # Se tiver um link real, provavelmete é navegação para outra aba/página
            try:
                a_tag = item.query_selector("a")
                if a_tag:
                    href = a_tag.get_attribute("href")
                    if href and href != "#" and not href.startswith("javascript"):
                        continue
            except Exception:
                pass

            try:
                item.click(timeout=2_000)
                page.wait_for_load_state("networkidle", timeout=6_000)
                time.sleep(0.5)
                clicked += 1
            except Exception:
                pass
        if clicked:
            print(f"     {clicked} categoria(s) clicada(s)", flush=True)
    except Exception:
        pass


def _pw_dom_links(page, tab_label) -> list[dict]:
    """
    Extrai todos os links de arquivo visíveis no DOM atual.
    Captura tudo — sem filtrar por ano aqui, pois o ano já foi
    controlado pelos dropdowns que foram selecionados antes desta chamada.
    O nome do arquivo é o texto do link ou o UUID da URL, nunca inferido.
    """
    try:
        raw = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({href: e.href, text: e.innerText.trim(), title: e.title || ''}))"
        )
    except Exception:
        return []
    out = []
    for item in raw:
        href = item.get("href", "")
        if not is_file_url(href):
            continue
        text = (item.get("text") or item.get("title") or "").strip()
        title = sanitize(text) if text else Path(urlparse(href).path).stem
        out.append({
            "url":   href,
            "title": title,
            "tab":   tab_label,
            "year":  None,   # ano não inferível aqui — controlado pelo dropdown
            "ext":   Path(urlparse(href).path).suffix.lower(),
            "source": "playwright-dom",
        })
    return out


# ──────────────────────────────────────────────────────────────
# CAMADA 3 — HTML ESTÁTICO (fallback)
# ──────────────────────────────────────────────────────────────

def static_scrape(url: str, session: requests.Session, tab_label: str) -> list[dict]:
    """Fallback: extrai links de arquivo do HTML estático. Captura tudo sem filtrar por ano."""
    try:
        r = session.get(url, headers=DEFAULT_HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"   ⚠ {e}")
        return []
    out = []
    for href in re.findall(r'href=["\'][^"\'>]+["\']', r.text):
        if not href.startswith("http"):
            href = urljoin(url, href)
        if not is_file_url(href):
            continue
        out.append({
            "url":   href,
            "title": sanitize(Path(urlparse(href).path).stem),
            "tab":   tab_label,
            "year":  None,
            "ext":   Path(urlparse(href).path).suffix.lower(),
            "source": "static",
        })
    return dedupe(out)


# ──────────────────────────────────────────────────────────────
# DOWNLOAD
# ──────────────────────────────────────────────────────────────

import hashlib

def compute_hash(file_path: Path) -> str:
    """Calcula o hash MD5 de um arquivo local."""
    h = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""

def download_all(links: list[dict], output_dir: Path,
                 session: requests.Session):
    """
    Baixa todos os arquivos.

    Estrutura de pastas:
      output_dir/
        <tab>/          ← nome legível da aba (ex: "Arteris", "Intervias")
          arquivo.pdf   ← SEM subpastas adicionais
    """
    print(f"\n⬇  Baixando {len(links)} arquivo(s) → '{output_dir}'")
    output_dir.mkdir(parents=True, exist_ok=True)
    ok = failed = skipped = 0
    manifest = []

    for link in tqdm(links, desc="Arquivos", ncols=88):
        tab   = sanitize(link.get("tab") or "Geral")
        title = link.get("title") or "arquivo"
        ext   = (link.get("ext") or
                 Path(urlparse(link["url"]).path).suffix.lower() or ".pdf")

        # Nome do arquivo: exatamente o título cadastrado na plataforma + extensão.
        # Sem prefixo de data, sem código de categoria, sem inferência.
        fname = f"{sanitize(title)}{ext}"

        # Estrutura: output_dir / <Nome da Aba> / arquivo.ext
        dest = output_dir / tab / fname

        if dest.exists() and dest.stat().st_size > 0:
            skipped += 1
            f_hash = compute_hash(dest)
            manifest.append({**link, "local": str(dest), "hash": f_hash, "status": "cached"})
            continue

        if download_file(link["url"], dest, session):
            ok += 1
            f_hash = compute_hash(dest)
            manifest.append({**link, "local": str(dest), "hash": f_hash, "status": "ok"})
        else:
            failed += 1
            manifest.append({**link, "local": None, "hash": None, "status": "failed"})

        time.sleep(REQUEST_DELAY)

    with open(output_dir / "manifesto.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {ok} baixados | {skipped} já existiam | {failed} falhas")
    print(f"   Manifesto: {output_dir / 'manifesto.json'}")


# ──────────────────────────────────────────────────────────────
# CAMADA 1b — WP-JSON MZ INTERNO (sites sem UUID externo, ex: Vtal)
# ──────────────────────────────────────────────────────────────

def _fetch_wp_json_mz(base_url: str, session: requests.Session,
                      from_year: int, to_year: int,
                      tab_label: str) -> list[dict]:
    """
    Busca documentos via endpoint interno do plugin MZ no WordPress.
    Usado por sites como Vtal que não expõem o UUID do mzfilemanager no HTML.

    Tenta os endpoints conhecidos do plugin mz-ir, sem filtro de categoria —
    baixa tudo e deixa o filtro de ano decidir o que manter.
    """
    candidates = [
        f"{base_url}/wp-json/mz-ir/v1/documents",
        f"{base_url}/wp-json/mz-ir/v2/documents",
        f"{base_url}/wp-json/mz/v1/documents",
        f"{base_url}/wp-json/mzir/v1/documents",
        f"{base_url}/?rest_route=/mz-ir/v1/documents",
    ]

    all_links = []
    for endpoint in candidates:
        print(f"       tentando {endpoint} ...", flush=True)
        # Busca paginada sem filtro de ano (deixa a API retornar tudo)
        page_num = 1
        found_any = False
        while True:
            data = fetch_json(endpoint, session,
                              {"per_page": 100, "page": page_num, "lang": "pt-br"})
            if not data:
                break
            docs = data if isinstance(data, list) else data.get("results", [])
            if not docs:
                break
            found_any = True
            for doc in docs:
                yr = doc.get("year")
                if yr is None:
                    d = doc.get("date") or doc.get("publishDate") or ""
                    if d and len(d) >= 4 and d[:4].isdigit():
                        yr = int(d[:4])
                if from_year and yr is not None and yr < from_year:
                    continue
                if to_year and yr is not None and yr > to_year:
                    continue

                # URL do arquivo — padrões comuns do plugin mz-ir
                file_url = None
                for field in ("file", "path", "url", "fileUrl", "link", "arquivo"):
                    v = doc.get(field)
                    if v and isinstance(v, str) and v.strip():
                        file_url = v if v.startswith("http") else urljoin(base_url, v)
                        break
                # Tenta campo aninhado (alguns plugins retornam {file: {url: ...}})
                if not file_url:
                    fobj = doc.get("file") or doc.get("arquivo")
                    if isinstance(fobj, dict):
                        file_url = fobj.get("url") or fobj.get("path")

                if not file_url:
                    continue

                raw_title = (doc.get("title") or doc.get("name") or "").strip()
                title = sanitize(raw_title) if raw_title else Path(urlparse(file_url).path).stem
                ext = Path(urlparse(file_url).path).suffix.lower() or ".pdf"

                all_links.append({
                    "url":    file_url,
                    "title":  title,
                    "tab":    tab_label,
                    "year":   yr,
                    "ext":    ext,
                    "source": "wp-json-mz",
                })

            if len(docs) < 100:
                break
            page_num += 1
            time.sleep(REQUEST_DELAY)

        if found_any:
            print(f"       ✓ endpoint funcionou: {endpoint}", flush=True)
            break  # não tenta os demais se este funcionou

    return dedupe(all_links)


# ──────────────────────────────────────────────────────────────
# ORQUESTRADOR PRINCIPAL
# ──────────────────────────────────────────────────────────────

def run(url: str, output_dir: Path,
        from_year: int = None, to_year: int = None,
        categories: list[str] = None,
        discover_only: bool = False,
        skip_playwright: bool = False,
        save_debug: bool = False,
        all_tabs: bool = True):

    session   = requests.Session()
    all_links: list[dict] = []

    print("=" * 64)
    print(f"  RI Downloader v4")
    print(f"  URL      : {url}")
    print(f"  Anos     : {from_year or 'todos'} → {to_year or 'todos'}")
    print(f"  Abas     : {'todas (automático)' if all_tabs else 'só esta URL'}")
    print("=" * 64)

    # ── 1. UUID MZiQ ───────────────────────────────────────────
    print("\n🔍 Detectando UUID MZiQ...")
    uuid = detect_uuid(url, session)

    # ── 2. Descoberta de abas ──────────────────────────────────
    print("\n📑 Descobrindo abas/sub-entidades...")
    if all_tabs:
        tabs = discover_tabs(url, session)
    else:
        slug = _url_slug(url)
        tabs = [{"slug": slug, "label": slug_to_label(slug), "url": url}]

    # ── 3. Processa cada aba ───────────────────────────────────
    for tab in tabs:
        label = tab["label"]
        t_url = tab["url"]

        print(f"\n{'─'*60}")
        print(f"  Aba  : {label}")
        print(f"  Pasta: {output_dir / label}")
        print(f"  URL  : {t_url}")

        # Camada 1: API MZiQ
        if uuid:
            print("  📡 Camada 1: API MZiQ...")
            api_links = mziq_fetch_tab(uuid, session, from_year, to_year,
                                       categories, label)
            print(f"     → {len(api_links)} arquivo(s)")
            all_links.extend(api_links)

        # Camada 1b: wp-json interno (para sites MZ sem UUID no HTML, ex: Vtal)
        if not uuid:
            print("  🔌 Camada 1b: wp-json/mz-ir interno...", flush=True)
            wp_base = f"{urlparse(t_url).scheme}://{urlparse(t_url).netloc}"
            wp_links = _fetch_wp_json_mz(wp_base, session, from_year, to_year, label)
            if wp_links:
                print(f"     → {len(wp_links)} arquivo(s) via wp-json", flush=True)
                all_links.extend(wp_links)
            else:
                print(f"     → endpoint wp-json não disponível", flush=True)

        # Camada 2: Playwright
        if not skip_playwright:
            print("  🌐 Camada 2: Playwright (browser headless)...")
            pw_links, api_calls = playwright_scrape(t_url, from_year, to_year, label)
            print(f"     → {len(pw_links)} arquivo(s) | {len(api_calls)} chamadas API interceptadas")
            all_links.extend(pw_links)

            # Salva chamadas interceptadas apenas se --debug foi passado
            if api_calls and save_debug:
                dbg_path = output_dir / "_debug" / f"api_calls_{sanitize(tab['slug'])}.json"
                dbg_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dbg_path, "w") as f:
                    json.dump(sorted(set(api_calls)), f, indent=2)
                print(f"     debug salvo: {dbg_path}", flush=True)

            if api_calls:
                # 1. Tenta extrair UUID se ainda não temos
                if not uuid:
                    for api_url in api_calls:
                        m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", api_url, re.IGNORECASE)
                        if m:
                            uuid = m.group(1)
                            print(f"   📡 UUID interceptado na rede: {uuid}. Recuperando via API MZiQ...")
                            extra_api = mziq_fetch_tab(uuid, session, from_year, to_year, categories, label)
                            print(f"     → {len(extra_api)} arquivo(s) recuperados da API!")
                            all_links.extend(extra_api)
                            break

                # 2. Tenta extrair arquivos dos conteúdos interceptados
                for api_url in api_calls:
                    if "mzfilemanager" in api_url and "contents" in api_url:
                        data = fetch_json(api_url, session)
                        if data:
                            extra = _mziq_to_links(
                                data if isinstance(data, list) else [data],
                                uuid or "", from_year, to_year, label
                            )
                            all_links.extend(extra)

        # Camada 3: Fallback HTML estático
        tab_count = sum(1 for l in all_links if l["tab"] == label)
        if tab_count == 0:
            print("  📄 Camada 3: HTML estático (fallback)...")
            static = static_scrape(t_url, session, label)
            print(f"     → {len(static)} arquivo(s)")
            all_links.extend(static)

    # ── 4. Deduplicação e filtro de ano ────────────────────────
    all_links = dedupe(all_links)

    if from_year or to_year:
        before     = len(all_links)
        kept       = []
        no_year    = []
        for l in all_links:
            yr = l.get("year")
            if yr is None:
                # Ano não inferível: mantém o arquivo (não queremos perder nada),
                # mas marca para inspeção manual no manifesto
                l["year_inferred"] = False
                no_year.append(l)
                kept.append(l)
            else:
                l["year_inferred"] = True
                if from_year and yr < from_year:
                    continue
                if to_year and yr > to_year:
                    continue
                kept.append(l)
        all_links = kept
        print(f"\n   Filtro de ano {from_year}→{to_year or 'hoje'}: "
              f"{before} doc(s) brutos → {len(all_links)} mantidos "
              f"({len(no_year)} sem metadado de ano — incluídos por segurança)", flush=True)

    # ── 5. Resumo ──────────────────────────────────────────────
    print(f"\n📋 Total de arquivos únicos: {len(all_links)}")
    by_tab = Counter(l.get("tab", "?") for l in all_links)
    for tab_name, n in sorted(by_tab.items()):
        print(f"   • {tab_name:40s}  {n:4d} arquivo(s)")

    # Salva catálogo completo
    output_dir.mkdir(parents=True, exist_ok=True)
    cat_path = output_dir / "catalogo.json"
    with open(cat_path, "w", encoding="utf-8") as f:
        json.dump(all_links, f, ensure_ascii=False, indent=2)
    print(f"\n   Catálogo: {cat_path}")

    if discover_only:
        print("\n[--discover-only] Encerrado sem downloads.")
        print("   Estrutura de pastas que seria criada:")
        for tab_name in sorted(by_tab):
            print(f"     {output_dir.name}/{tab_name}/")
        return

    if not all_links:
        print("\n⚠  Nenhum arquivo encontrado.")
        print("   Dica: use --discover-only e inspecione os arquivos _debug_api_*.json")
        return

    download_all(all_links, output_dir, session)


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Downloader de documentos RI — plataforma MZ Group / MZiQ",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  # Arteris — todas as 8 abas, 2022+
  python utils_ri_downloader.py --url https://ri.arteris.com.br/informacoes-aos-investidores/central-de-resultados/arteris/ --from-year 2022 --out ./Arteris

  # Iguá — todas as abas (Grupo + SPEs), 2023+
  python utils_ri_downloader.py --url https://ri.igua.com.br/informacoes-aos-investidores/central-de-resultados/ --from-year 2023 --out ./Igua

  # Aegea — 2023+
  python utils_ri_downloader.py --url https://ri.aegea.com.br/informacoes-aos-investidores/central-de-resultados/ --from-year 2023 --out ./Aegea

  # Só a aba Intervias (sem descobrir as irmãs)
  python utils_ri_downloader.py --url https://ri.arteris.com.br/informacoes-aos-investidores/central-de-resultados/intervias/ --from-year 2023 --no-all-tabs --out ./Arteris

  # Só descobrir — mostra estrutura de pastas sem baixar nada
  python utils_ri_downloader.py --url https://ri.arteris.com.br/informacoes-aos-investidores/central-de-resultados/arteris/ --from-year 2023 --discover-only --out ./Arteris
        """
    )
    p.add_argument("--url",           required=True,
                   help="URL da Central de Resultados (qualquer aba)")
    p.add_argument("--out",           default="./ri_docs",
                   help="Pasta raiz de saída (ex: ./Arteris)")
    p.add_argument("--from-year",     type=int, default=None,
                   help="Ano inicial inclusive (ex: 2023). Se omitido, baixa todos os anos disponíveis.")
    p.add_argument("--to-year",       type=int, default=None,
                   help="Ano final (ex: 2025)")
    p.add_argument("--categories",    default=None,
                   help="Slugs de categoria separados por vírgula "
                        "(ex: demonstracoes-financeiras,escritura-de-emissao)")
    p.add_argument("--discover-only", action="store_true",
                   help="Apenas cataloga sem baixar arquivos")
    p.add_argument("--no-playwright", action="store_true",
                   help="Pula a fase do browser Playwright")
    p.add_argument("--debug",        action="store_true",
                   help="Salva arquivos de diagnóstico de chamadas de API em _debug/")
    p.add_argument("--no-all-tabs",   action="store_true",
                   help="Processa só a URL passada (sem descobrir abas irmãs)")
    args = p.parse_args()

    run(
        url             = args.url,
        output_dir      = Path(args.out),
        from_year       = args.from_year,
        to_year         = args.to_year,
        categories      = [c.strip() for c in args.categories.split(",")]
                          if args.categories else None,
        discover_only   = args.discover_only,
        skip_playwright = args.no_playwright,
        save_debug      = args.debug,
        all_tabs        = not args.no_all_tabs,
    )


if __name__ == "__main__":
    main()