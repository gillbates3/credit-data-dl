"""
Script: tmp/comparar_modelos_extracao.py
Descrição: Harness DESCARTÁVEL de comparação entre modelos Gemini (ex.: gemini-2.5-flash
           vs gemini-3.1-flash-lite) nas duas trilhas de extração do projeto
           (qualitativa = Markdown; quantitativa = JSON CVM).

           NÃO altera código de produção. Reaproveita os prompts/helpers dos serviços
           (scripts_v2/servico_ia_qualitativa.py e servico_ia_quantitativa.py) e faz
           chamadas Gemini INSTRUMENTADAS, capturando o que os serviços não expõem:
           finish_reason (truncamento), usage_metadata (tokens) e latência. Calcula
           custo em USD e gera um relatório lado a lado para decisão do dono.

Uso:
    # listar ids de modelos disponíveis na conta (confirmar o id do 3.1 Flash-Lite)
    python tmp/comparar_modelos_extracao.py --listar-modelos

    # estimativa de custo/contagem de chunks SEM chamar a API
    python tmp/comparar_modelos_extracao.py --limite 3 --dry-run

    # comparação real (gasta tokens nos dois modelos)
    python tmp/comparar_modelos_extracao.py --limite 3 --modo ambos
    python tmp/comparar_modelos_extracao.py --arquivos formulario_de_referencia,escritura --modo ambos
"""

import argparse
import io
import json
import re
import sys
import time
from pathlib import Path

# --- Permite importar o pacote scripts_v2 a partir de tmp/ -------------------
PROJETO_RAIZ = Path(__file__).resolve().parent.parent
if str(PROJETO_RAIZ) not in sys.path:
    sys.path.insert(0, str(PROJETO_RAIZ))

import pdfplumber  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402
from google.genai import types  # noqa: E402

from scripts_v2 import servico_ia_qualitativa as qual  # noqa: E402
from scripts_v2 import servico_ia_quantitativa as quant  # noqa: E402

# Reusa o mesmo client/key dos serviços (carrega .env.local no import).
CLIENT = qual.CLIENT

# --- Configuração de modelos (preços oficiais jun/2026, USD / 1M tokens) -----
# Confirme o id exato do 3.1 Flash-Lite com --listar-modelos antes de rodar pra valer.
MODELOS = [
    {"id": "gemini-2.5-flash", "preco_in": 0.30, "preco_out": 2.50, "thinking_budget": 0},
    {"id": "gemini-3.1-flash-lite", "preco_in": 0.25, "preco_out": 1.50, "thinking_budget": 0},
]

PAGINAS_POR_CHUNK_TEXTO = 8       # restrição firme do dono (evita truncamento)
PAGINAS_POR_CHUNK_VISION = qual.VISION_PAGES_PER_CHUNK  # 15
SAIDA_DIR = Path(__file__).resolve().parent / "comparacao_modelos"

PADRAO_NUMERO = re.compile(r"\d[\d.,]*\d|\d")

# --- Overrides de runtime (setados em main via CLI) -------------------------
REFORCO = False
TAG = ""
THINKING_OVERRIDE = "padrao"  # "padrao" = usa o do MODELOS; int = sobrescreve

REFORCO_QUAL = """

REFORÇO CRÍTICO (NÃO IGNORE):
- NÃO RESUMA a narrativa: transcreva na íntegra os parágrafos da administração, comentários de desempenho operacional/financeiro, fatores de risco e justificativas. Preserve o texto; não condense em bullets curtos.
- Transcreva TODOS os números e TODAS as colunas: tanto trimestrais (ex.: 4T25, 4T24, ∆%) quanto anuais (ex.: 2025, 2024, ∆%). Não colapse colunas nem mantenha apenas o valor anual.
- Não condense tabelas: cada linha/item deve aparecer com todos os seus valores por período.
"""

REFORCO_QUANT = (
    "\n\nIMPORTANTE: extraia TODAS as contas de TODAS as demonstrações presentes "
    "(BPA, BPP, DRE, DFC, DVA), sem omitir linhas, incluindo subcontas detalhadas e seus códigos."
)


def _budget_efetivo(tb):
    return tb if THINKING_OVERRIDE == "padrao" else THINKING_OVERRIDE


# ---------------------------------------------------------------------------
# Infra de chamada instrumentada
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _preco_modelo(model_id: str) -> dict:
    for m in MODELOS:
        if m["id"] == model_id:
            return m
    return {"preco_in": 0.0, "preco_out": 0.0, "thinking_budget": None}


def _config_qual(thinking_budget):
    kwargs = {"temperature": 0.0}
    if thinking_budget is not None:
        try:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)
        except Exception:
            pass
    return types.GenerateContentConfig(**kwargs)


def _config_quant(periodos_existentes, thinking_budget):
    kwargs = {
        "system_instruction": quant.system_instruction_quantitativa(periodos_existentes or []),
        "temperature": 0.0,
        "response_mime_type": "application/json",
    }
    if thinking_budget is not None:
        try:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)
        except Exception:
            pass
    return types.GenerateContentConfig(**kwargs)


def _usage(resp) -> dict:
    u = getattr(resp, "usage_metadata", None)
    if u is None:
        return {"prompt": 0, "saida": 0, "thinking": 0}
    return {
        "prompt": getattr(u, "prompt_token_count", 0) or 0,
        "saida": getattr(u, "candidates_token_count", 0) or 0,
        "thinking": getattr(u, "thoughts_token_count", 0) or 0,
    }


def _finish_reason(resp) -> str:
    try:
        fr = resp.candidates[0].finish_reason
    except Exception:
        return "DESCONHECIDO"
    return getattr(fr, "name", str(fr)) if fr is not None else "DESCONHECIDO"


def chamar_instrumentado(model_id: str, contents, config) -> dict:
    """Chama generate_content capturando texto, truncamento, tokens, latência e custo."""
    preco = _preco_modelo(model_id)
    for tentativa in range(3):
        inicio = time.perf_counter()
        try:
            resp = CLIENT.models.generate_content(model=model_id, contents=contents, config=config)
            latencia = time.perf_counter() - inicio
            uso = _usage(resp)
            finish = _finish_reason(resp)
            custo = (
                uso["prompt"] / 1e6 * preco["preco_in"]
                + (uso["saida"] + uso["thinking"]) / 1e6 * preco["preco_out"]
            )
            return {
                "ok": True,
                "texto": (resp.text or "") if hasattr(resp, "text") else "",
                "finish_reason": finish,
                "truncado": finish == "MAX_TOKENS",
                "latencia_s": latencia,
                "tokens": uso,
                "custo_usd": custo,
            }
        except Exception as e:
            err = str(e)
            if any(c in err for c in ("429", "503", "UNAVAILABLE")):
                espera = (tentativa + 1) * 15
                log(f"    [{model_id}] erro transitório ({err[:80]}). Aguardando {espera}s...")
                time.sleep(espera)
                continue
            log(f"    [{model_id}] erro: {err[:200]}")
            return {
                "ok": False, "texto": "", "finish_reason": "ERRO", "truncado": False,
                "latencia_s": time.perf_counter() - inicio,
                "tokens": {"prompt": 0, "saida": 0, "thinking": 0}, "custo_usd": 0.0,
                "erro": err[:300],
            }
    return {
        "ok": False, "texto": "", "finish_reason": "ERRO_RETRY", "truncado": False,
        "latencia_s": 0.0, "tokens": {"prompt": 0, "saida": 0, "thinking": 0},
        "custo_usd": 0.0, "erro": "esgotou retries",
    }


def _agrega_chunks(chunks: list[dict]) -> dict:
    return {
        "n_chunks": len(chunks),
        "n_truncados": sum(1 for c in chunks if c.get("truncado")),
        "finish_reasons": [c.get("finish_reason") for c in chunks],
        "latencia_s": round(sum(c.get("latencia_s", 0) for c in chunks), 2),
        "tokens_prompt": sum(c["tokens"]["prompt"] for c in chunks),
        "tokens_saida": sum(c["tokens"]["saida"] for c in chunks),
        "tokens_thinking": sum(c["tokens"]["thinking"] for c in chunks),
        "custo_usd": round(sum(c.get("custo_usd", 0) for c in chunks), 6),
    }


def _numeros(texto: str) -> list[str]:
    return PADRAO_NUMERO.findall(texto or "")


# ---------------------------------------------------------------------------
# Trilha qualitativa (espelha _gerar_markdown_llm / processar_pdf_texto_por_lotes)
# ---------------------------------------------------------------------------
def _detectar_scanned(conteudo: bytes) -> tuple[int, bool]:
    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        total = len(pdf.pages)
        com_texto = 0
        for p in pdf.pages:
            txt = (p.extract_text() or "").strip()
            if len(txt) >= qual.MIN_TEXT_CHARS_PER_PAGE:
                com_texto += 1
    is_scanned = total > 0 and com_texto < (total * 0.1)
    return total, is_scanned


def _chunks_texto(conteudo: bytes) -> list[tuple[int, int, str]]:
    """Retorna lista de (pag_inicio, pag_fim, texto_sanitizado) por fatia de 8 páginas."""
    fatias = []
    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        pages = pdf.pages
        total = len(pages)
        for i in range(0, total, PAGINAS_POR_CHUNK_TEXTO):
            chunk_pages = pages[i : i + PAGINAS_POR_CHUNK_TEXTO]
            partes = []
            for offset, page in enumerate(chunk_pages):
                txt = (page.extract_text() or "").strip()
                if len(txt) >= qual.MIN_TEXT_CHARS_PER_PAGE:
                    partes.append(f"\n\n--- PÁGINA {i + offset + 1} ---\n{txt}")
            bruto = "".join(partes).strip()
            if not bruto:
                continue
            limpo, _ = qual.sanitize_extracted_text(bruto)
            fatias.append((i + 1, i + len(chunk_pages), limpo))
    return fatias


def processar_qual(model_id: str, thinking_budget, cnpj: str, nome: str, conteudo: bytes) -> dict:
    total, is_scanned = _detectar_scanned(conteudo)
    chunks_meta: list[dict] = []
    partes_md: list[str] = []

    if total == 0:
        return {"erro": "PDF sem páginas", "modo": "vazio"}

    if not is_scanned:
        modo = "texto"
        config = _config_qual(thinking_budget)
        fatias = _chunks_texto(conteudo)
        for pi, pf, texto in fatias:
            nome_chunk = f"{nome} (Páginas {pi} a {pf} de {total})"
            prompt = (
                f"CNPJ: {cnpj}\nArquivo: {nome_chunk}\n\n{qual.PROMPT_QUALITATIVO}"
                f"{REFORCO_QUAL if REFORCO else ''}\n\n"
                f"Texto extraído do PDF:\n{texto}"
            )
            log(f"    [qual/{model_id}] chunk páginas {pi}-{pf}/{total}...")
            r = chamar_instrumentado(model_id, prompt, config)
            chunks_meta.append(r)
            if r["ok"] and r["texto"]:
                partes_md.append(r["texto"])
    else:
        modo = "vision"
        config = _config_qual(thinking_budget)
        reader = PdfReader(io.BytesIO(conteudo))
        total = len(reader.pages)
        for i in range(0, total, PAGINAS_POR_CHUNK_VISION):
            pi, pf = i + 1, min(i + PAGINAS_POR_CHUNK_VISION, total)
            writer = PdfWriter()
            for idx in range(i, pf):
                writer.add_page(reader.pages[idx])
            buf = io.BytesIO()
            writer.write(buf)
            nome_chunk = f"{nome} (Páginas {pi} a {pf} de {total})"
            log(f"    [qual/{model_id}] VISION chunk páginas {pi}-{pf}/{total}...")
            r = _chamar_vision(model_id, config, cnpj, nome_chunk, buf.getvalue())
            chunks_meta.append(r)
            if r["ok"] and r["texto"]:
                partes_md.append(r["texto"])

    markdown_bruto = "\n\n".join(partes_md).strip()
    markdown, _ = qual.sanitize_generated_markdown(markdown_bruto) if markdown_bruto else ("", 0)
    agg = _agrega_chunks(chunks_meta)
    agg.update({
        "modo": modo,
        "total_paginas": total,
        "chars_saida": len(markdown),
        "n_numeros": len(_numeros(markdown)),
        "markdown": markdown,
    })
    return agg


def _chamar_vision(model_id, config, cnpj, nome, conteudo) -> dict:
    """Upload + generate_content instrumentado para PDF escaneado (uma fatia)."""
    import os
    import tempfile

    uploaded = None
    temp_path = None
    preco = _preco_modelo(model_id)
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(conteudo)
            temp_path = tmp.name
        uploaded = CLIENT.files.upload(
            file=temp_path, config=types.UploadFileConfig(mime_type="application/pdf")
        )
        while qual.file_state_name(CLIENT.files.get(name=uploaded.name)) == "PROCESSING":
            time.sleep(2)
        file_info = CLIENT.files.get(name=uploaded.name)
        if qual.file_state_name(file_info) == "FAILED":
            return {"ok": False, "texto": "", "finish_reason": "UPLOAD_FAILED", "truncado": False,
                    "latencia_s": 0.0, "tokens": {"prompt": 0, "saida": 0, "thinking": 0}, "custo_usd": 0.0}
        prompt = f"CNPJ: {cnpj}\nArquivo: {nome}\n\n{qual.PROMPT_QUALITATIVO}{REFORCO_QUAL if REFORCO else ''}"
        inicio = time.perf_counter()
        resp = CLIENT.models.generate_content(model=model_id, contents=[prompt, file_info], config=config)
        latencia = time.perf_counter() - inicio
        uso = _usage(resp)
        finish = _finish_reason(resp)
        custo = uso["prompt"] / 1e6 * preco["preco_in"] + (uso["saida"] + uso["thinking"]) / 1e6 * preco["preco_out"]
        return {"ok": True, "texto": resp.text or "", "finish_reason": finish,
                "truncado": finish == "MAX_TOKENS", "latencia_s": latencia, "tokens": uso, "custo_usd": custo}
    except Exception as e:
        return {"ok": False, "texto": "", "finish_reason": "ERRO", "truncado": False, "latencia_s": 0.0,
                "tokens": {"prompt": 0, "saida": 0, "thinking": 0}, "custo_usd": 0.0, "erro": str(e)[:300]}
    finally:
        if uploaded is not None:
            try:
                CLIENT.files.delete(name=uploaded.name)
            except Exception:
                pass
        if temp_path:
            try:
                import os
                os.unlink(temp_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Trilha quantitativa (espelha extrair_dados_quantitativos, 1 arquivo)
# ---------------------------------------------------------------------------
def processar_quant(model_id: str, thinking_budget, cnpj: str, nome: str, conteudo: bytes,
                    periodos_existentes=None) -> dict:
    if not quant.is_financial_pdf_name(nome):
        return {"pulado": True, "motivo": "heuristica_nome_nao_financeiro"}

    texto, is_scanned = quant.extract_financial_pages_text_from_bytes(conteudo, nome)
    config = _config_quant(periodos_existentes, thinking_budget)

    if texto and not is_scanned:
        prompt = (
            f"CNPJ: {cnpj}\nArquivo: {nome}\n\n"
            f"Texto das páginas financeiras extraído do PDF:\n{texto}\n\n"
            f"Extraia os dados financeiros no formato JSON conforme instruído."
            f"{REFORCO_QUANT if REFORCO else ''}"
        )
        r = chamar_instrumentado(model_id, prompt, config)
    else:
        r = _chamar_vision(model_id, config, cnpj, nome, conteudo)

    consolidated = quant.criar_json_base(cnpj)
    n_periodos = 0
    parsed = None
    if r["ok"] and r["texto"]:
        try:
            parsed = quant.normalizar_resposta_ia(json.loads(r["texto"]))
        except Exception:
            parsed = None
        if parsed:
            n_periodos = quant.merge_periods(consolidated, parsed)

    n_contas = sum(
        len(contas)
        for periodo in consolidated.get("periodos", {}).values()
        for contas in periodo.get("demonstracoes", {}).values()
        if isinstance(contas, dict)
    )
    return {
        "pulado": False,
        "modo": "texto" if (texto and not is_scanned) else "vision",
        "ok": r["ok"],
        "finish_reason": r["finish_reason"],
        "truncado": r["truncado"],
        "latencia_s": round(r["latencia_s"], 2),
        "tokens_prompt": r["tokens"]["prompt"],
        "tokens_saida": r["tokens"]["saida"],
        "tokens_thinking": r["tokens"]["thinking"],
        "custo_usd": round(r["custo_usd"], 6),
        "n_periodos": len(consolidated.get("periodos", {})),
        "n_periodos_novos": n_periodos,
        "n_contas": n_contas,
        "json": consolidated,
    }


# ---------------------------------------------------------------------------
# Dry-run (sem API)
# ---------------------------------------------------------------------------
def dry_run(arquivos, cnpj, modo):
    log("=== DRY-RUN (sem chamadas à API) ===")
    total_chunks_qual = 0
    for nome, conteudo in arquivos:
        total, is_scanned = _detectar_scanned(conteudo)
        if modo in ("qual", "ambos"):
            if not is_scanned:
                fatias = _chunks_texto(conteudo)
                chars = sum(len(t) for _, _, t in fatias)
                total_chunks_qual += len(fatias)
                log(f"  {nome[:60]:60} | {total:>3} págs | qual: {len(fatias)} chunk(s) texto | ~{chars // 4:,} tok in")
            else:
                n = -(-total // PAGINAS_POR_CHUNK_VISION)
                total_chunks_qual += n
                log(f"  {nome[:60]:60} | {total:>3} págs | qual: {n} chunk(s) VISION (escaneado)")
        if modo in ("quant", "ambos"):
            if quant.is_financial_pdf_name(nome):
                texto, sc = quant.extract_financial_pages_text_from_bytes(conteudo, nome)
                log(f"  {' ':60} | quant: 1 chamada | ~{len(texto) // 4:,} tok in | {'vision' if sc or not texto else 'texto'}")
            else:
                log(f"  {' ':60} | quant: PULADO (heurística de nome)")
    n_quant = sum(1 for n, _ in arquivos if quant.is_financial_pdf_name(n)) if modo in ("quant", "ambos") else 0
    n_qual = total_chunks_qual if modo in ("qual", "ambos") else 0
    req_por_modelo = n_qual + n_quant
    log("-" * 80)
    log(f"Requisições por modelo: {req_por_modelo}  (qual={n_qual} chunks + quant={n_quant} arquivos)")
    log(f"Total estimado em {len(MODELOS)} modelo(s): {req_por_modelo * len(MODELOS)} requisições")
    log("Custo de OUTPUT não é estimável sem rodar (depende do tamanho da transcrição).")


# ---------------------------------------------------------------------------
# Execução real + relatório
# ---------------------------------------------------------------------------
def executar(arquivos, cnpj, modo):
    SAIDA_DIR.mkdir(parents=True, exist_ok=True)
    relatorio = {"cnpj": cnpj, "modo": modo, "modelos": [m["id"] for m in MODELOS], "arquivos": []}

    for nome, conteudo in arquivos:
        log(f"\n=== Arquivo: {nome} ({len(conteudo) / 1024:,.0f} KB) ===")
        item = {"arquivo": nome, "tamanho_kb": round(len(conteudo) / 1024, 1), "qual": {}, "quant": {}}

        for m in MODELOS:
            mid = m["id"]
            tb = _budget_efetivo(m["thinking_budget"])
            slug = (mid + (f"__{TAG}" if TAG else "")).replace("/", "_")
            (SAIDA_DIR / "por_modelo" / slug).mkdir(parents=True, exist_ok=True)

            if modo in ("qual", "ambos"):
                log(f"  -> QUAL com {mid}")
                rq = processar_qual(mid, tb, cnpj, nome, conteudo)
                md = rq.pop("markdown", "")
                (SAIDA_DIR / "por_modelo" / slug / f"{nome}.qual.md").write_text(md, encoding="utf-8")
                item["qual"][mid] = rq

            if modo in ("quant", "ambos"):
                log(f"  -> QUANT com {mid}")
                rqt = processar_quant(mid, tb, cnpj, nome, conteudo)
                js = rqt.pop("json", None)
                if js is not None:
                    (SAIDA_DIR / "por_modelo" / slug / f"{nome}.quant.json").write_text(
                        json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                item["quant"][mid] = rqt

        # heurística de fidelidade numérica entre modelos (qual)
        if modo in ("qual", "ambos") and len(MODELOS) == 2:
            a, b = MODELOS[0]["id"], MODELOS[1]["id"]
            na = set(_numeros((SAIDA_DIR / "por_modelo" / a.replace("/", "_") / f"{nome}.qual.md").read_text(encoding="utf-8")))
            nb = set(_numeros((SAIDA_DIR / "por_modelo" / b.replace("/", "_") / f"{nome}.qual.md").read_text(encoding="utf-8")))
            item["fidelidade_numerica_qual"] = {
                "modelo_a": a, "modelo_b": b,
                "numeros_a": len(na), "numeros_b": len(nb),
                "so_em_a": len(na - nb), "so_em_b": len(nb - na), "em_comum": len(na & nb),
            }

        relatorio["arquivos"].append(item)

    nome_rel = f"relatorio{('_' + TAG) if TAG else ''}"
    (SAIDA_DIR / f"{nome_rel}.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    _escrever_relatorio_md(relatorio, modo, nome_rel)
    log(f"\nRelatório salvo em {SAIDA_DIR} ({nome_rel}.md)")


def _escrever_relatorio_md(relatorio, modo, nome_rel="relatorio"):
    L = ["# Comparação de modelos — extração de PDFs", "",
         f"- CNPJ: `{relatorio['cnpj']}`  |  Modo: `{modo}`  |  Modelos: {', '.join(relatorio['modelos'])}",
         "- **Critério final = leitura humana das saídas** em `por_modelo/`. As tabelas abaixo apontam onde olhar.", ""]

    if modo in ("qual", "ambos"):
        L += ["## Trilha qualitativa (markdown)", "",
              "| Arquivo | Modelo | Modo | Chunks | **Truncados** | Latência (s) | Tok in | Tok out | Tok think | Custo USD | Chars | Nº números |",
              "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for it in relatorio["arquivos"]:
            for mid, r in it.get("qual", {}).items():
                if r.get("erro"):
                    L.append(f"| {it['arquivo'][:40]} | {mid} | ERRO | - | - | - | - | - | - | - | - | - |")
                    continue
                L.append(
                    f"| {it['arquivo'][:40]} | {mid} | {r.get('modo','')} | {r.get('n_chunks',0)} | "
                    f"{r.get('n_truncados',0)} | {r.get('latencia_s',0)} | {r.get('tokens_prompt',0)} | "
                    f"{r.get('tokens_saida',0)} | {r.get('tokens_thinking',0)} | {r.get('custo_usd',0):.4f} | "
                    f"{r.get('chars_saida',0)} | {r.get('n_numeros',0)} |"
                )
        L.append("")
        L.append("### Fidelidade numérica (divergência entre modelos, qual)")
        L.append("| Arquivo | Nº A | Nº B | Só em A | Só em B | Em comum |")
        L.append("|---|---:|---:|---:|---:|---:|")
        for it in relatorio["arquivos"]:
            f = it.get("fidelidade_numerica_qual")
            if f:
                L.append(f"| {it['arquivo'][:40]} | {f['numeros_a']} | {f['numeros_b']} | {f['so_em_a']} | {f['so_em_b']} | {f['em_comum']} |")
        L.append("")

    if modo in ("quant", "ambos"):
        L += ["## Trilha quantitativa (JSON CVM)", "",
              "| Arquivo | Modelo | Modo | **Trunc.** | Latência (s) | Tok in | Tok out | Custo USD | Períodos | Contas |",
              "|---|---|---|---|---:|---:|---:|---:|---:|---:|"]
        for it in relatorio["arquivos"]:
            for mid, r in it.get("quant", {}).items():
                if r.get("pulado"):
                    L.append(f"| {it['arquivo'][:40]} | {mid} | PULADO ({r.get('motivo','')}) | - | - | - | - | - | - | - |")
                    continue
                L.append(
                    f"| {it['arquivo'][:40]} | {mid} | {r.get('modo','')} | {'SIM' if r.get('truncado') else 'não'} | "
                    f"{r.get('latencia_s',0)} | {r.get('tokens_prompt',0)} | {r.get('tokens_saida',0)} | "
                    f"{r.get('custo_usd',0):.4f} | {r.get('n_periodos',0)} | {r.get('n_contas',0)} |"
                )
        L.append("")

    # agregado por modelo
    L += ["## Agregado por modelo", "", "| Modelo | Custo USD total | Latência total (s) | Chunks truncados (qual) |",
          "|---|---:|---:|---:|"]
    for mid in relatorio["modelos"]:
        custo = sum(it.get("qual", {}).get(mid, {}).get("custo_usd", 0) for it in relatorio["arquivos"])
        custo += sum(it.get("quant", {}).get(mid, {}).get("custo_usd", 0) for it in relatorio["arquivos"])
        lat = sum(it.get("qual", {}).get(mid, {}).get("latencia_s", 0) for it in relatorio["arquivos"])
        lat += sum(it.get("quant", {}).get(mid, {}).get("latencia_s", 0) for it in relatorio["arquivos"])
        trunc = sum(it.get("qual", {}).get(mid, {}).get("n_truncados", 0) for it in relatorio["arquivos"])
        L.append(f"| {mid} | {custo:.4f} | {round(lat, 1)} | {trunc} |")

    (SAIDA_DIR / f"{nome_rel}.md").write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------------------
def selecionar_arquivos(pasta: Path, filtros: list[str], limite: int):
    todos = qual.carregar_arquivos_em_memoria(pasta)
    if filtros:
        f = [s.lower() for s in filtros]
        todos = [(n, c) for (n, c) in todos if any(s in n.lower() for s in f)]
    return todos[:limite] if limite else todos


def main():
    ap = argparse.ArgumentParser(description="Compara modelos Gemini nas trilhas de extração.")
    ap.add_argument("pasta", nargs="?",
                    default=str(PROJETO_RAIZ / "data" / "01_landing" / "manual_uploads" / "02041460000193" / "Principal"),
                    help="Pasta com PDFs (default: corpus V.tal).")
    ap.add_argument("--cnpj", default="02041460000193")
    ap.add_argument("--limite", type=int, default=3, help="Máx. de arquivos (default 3; gasta tokens reais).")
    ap.add_argument("--arquivos", default="", help="Filtro por substrings no nome, separadas por vírgula.")
    ap.add_argument("--modo", choices=["qual", "quant", "ambos"], default="ambos")
    ap.add_argument("--dry-run", action="store_true", help="Estima custo/chunks sem chamar a API.")
    ap.add_argument("--listar-modelos", action="store_true", help="Lista ids de modelos disponíveis e sai.")
    ap.add_argument("--apenas-modelo", default="", help="Roda só este id de modelo (ex.: gemini-3.1-flash-lite).")
    ap.add_argument("--thinking", default=None, help="Override do thinking_budget (-1 dinâmico, 0 off, >0 cap).")
    ap.add_argument("--reforco", action="store_true", help="Acrescenta reforço anti-resumo ao prompt (qual+quant).")
    ap.add_argument("--tag", default="", help="Sufixo p/ pastas/relatório (evita sobrescrever runs anteriores).")
    args = ap.parse_args()

    global REFORCO, TAG, THINKING_OVERRIDE, MODELOS
    REFORCO = args.reforco
    TAG = args.tag
    if args.thinking is not None:
        THINKING_OVERRIDE = int(args.thinking)
    if args.apenas_modelo:
        MODELOS = [m for m in MODELOS if m["id"] == args.apenas_modelo]
        if not MODELOS:
            raise SystemExit(f"Modelo não encontrado em MODELOS: {args.apenas_modelo}")

    if args.listar_modelos:
        log("Modelos disponíveis na conta:")
        for m in CLIENT.models.list():
            print("  ", getattr(m, "name", m))
        return

    pasta = Path(args.pasta)
    if not pasta.exists():
        raise SystemExit(f"Pasta não encontrada: {pasta}")

    filtros = [s.strip() for s in args.arquivos.split(",") if s.strip()]
    arquivos = selecionar_arquivos(pasta, filtros, args.limite)
    if not arquivos:
        raise SystemExit("Nenhum PDF selecionado (confira --arquivos / --limite / pasta).")

    log(f"Selecionados {len(arquivos)} arquivo(s):")
    for n, c in arquivos:
        log(f"  - {n} ({len(c) / 1024:,.0f} KB)")

    if args.dry_run:
        dry_run(arquivos, args.cnpj, args.modo)
        return

    executar(arquivos, args.cnpj, args.modo)


if __name__ == "__main__":
    main()
