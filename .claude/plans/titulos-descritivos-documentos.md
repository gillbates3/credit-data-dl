# Plano: Título descritivo para documentos (nome do arquivo vira só referência interna)

> **Entrega:** spec autocontido para um agente executor (Codex). Assuma que ele **não** tem o histórico desta conversa. Idioma do projeto: **pt-BR**. Plataforma: **Windows**.

## Context

Hoje, ao ingerir PDFs, o sistema salva apenas `nome_arquivo` (em `emissor_compendio_qualitativo` e `emissor_compendio_quantitativo`). Esse nome costuma ser um UUID sem sentido (ex.: `19be6779-217e-328f-c1ea-8b8e28c018fb.pdf`), e é exibido tanto como **título** quanto como **referência** na lista de Markdowns ([servico_repositorio.py](scripts_v2/servico_repositorio.py) monta o item com `titulo = nome_arquivo` e `origem = nome_arquivo`; [markdown-viewer.tsx](frontend/components/markdown-viewer.tsx) renderiza `titulo` em destaque e `origem` em cinza).

**Objetivo:** manter `nome_arquivo` no banco apenas como **referência interna**, e gerar/persistir um **título descritivo baseado no conteúdo real** do documento (ex.: "Demonstrações Financeiras Dez2025", "ITR Mar2026", "Escritura 2ª Emissão VPLT", "Rating 2ª Emissão VPLT Ago2022"), usado em todas as exibições. O título é gerado por LLM a partir do markdown que já é produzido na ingestão.

## Decisões travadas (definidas pelo dono do produto)

| Decisão | Escolha |
|---|---|
| Geração do título | **LLM sobre o markdown já extraído** (1 chamada curta ao Gemini, sobre o início do markdown). Entende ITR/DFP/escritura/rating. |
| Registros já existentes | **Forward-only** — sem script de backfill. Só novos uploads ganham título; os antigos seguem mostrando o nome do arquivo (fallback). |
| Manifesto quantitativo | **Unificar** — gerar o título uma vez por arquivo e gravar nas duas tabelas (qualitativo e quantitativo). |

## Convenção de nomenclatura (encodar no prompt)
- pt-BR, **conciso** (≤ ~60 caracteres), sem extensão, sem aspas, sem markdown, uma linha só.
- Padrão: `<Tipo do documento> [<emissão/série/identificador, se houver>] <Período abreviado>`.
- Período abreviado: `MmmAAAA` (ex.: `Dez2025`, `Mar2026`), trimestre (`3T2025`) ou intervalo quando aplicável.
- Exemplos-alvo: `Demonstrações Financeiras Dez2025` · `ITR Mar2026` · `Escritura 2ª Emissão VPLT` · `Rating 2ª Emissão VPLT Ago2022` · `Release de Resultados 3T2025`.
- Se não der para inferir com confiança, retornar algo neutro (ex.: `Documento <data se houver>`); o orquestrador faz fallback final para o nome do arquivo sem extensão.

---

## Tarefa 1 — Schema (`scripts_v2/sql/supabase_schema_v2.sql` + migração no Supabase)

Adicionar a coluna `titulo text` (nullable) nas duas tabelas de compêndio.

1. **No arquivo de schema** (para instalações limpas): adicionar `titulo text,` em `emissor_compendio_qualitativo` ([linhas 240-249](scripts_v2/sql/supabase_schema_v2.sql#L240-L249)) e `emissor_compendio_quantitativo` ([linhas 261-269](scripts_v2/sql/supabase_schema_v2.sql#L261-L269)).
2. **Migração no banco vivo** (forward-only, sem DROP — executar no SQL Editor do Supabase):
   ```sql
   ALTER TABLE public.emissor_compendio_qualitativo  ADD COLUMN IF NOT EXISTS titulo text;
   ALTER TABLE public.emissor_compendio_quantitativo ADD COLUMN IF NOT EXISTS titulo text;
   ```

---

## Tarefa 2 — Geração do título (`scripts_v2/servico_ia_qualitativa.py`)

Nova função pública que recebe o markdown já produzido e devolve um título curto:

```python
def gerar_titulo_documento(cnpj: str, nome_arquivo: str, markdown: str) -> str:
    """Gera um título descritivo a partir do conteúdo (markdown) do documento.
    Fallback para o nome do arquivo (sem extensão) em qualquer falha/vazio."""
    fallback = Path(nome_arquivo).stem or nome_arquivo or "Documento"
    trecho = (markdown or "").strip()[:6000]   # capa/cabeçalho/período ficam no início
    if not trecho:
        return fallback
    prompt = PROMPT_TITULO + f"\n\nCNPJ: {cnpj}\nArquivo: {nome_arquivo}\n\nConteúdo (início):\n{trecho}"
    try:
        response = CLIENT.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0),
        )
        titulo = (response.text or "").strip().splitlines()[0].strip().strip('"').strip("#").strip()
        return titulo[:80] if titulo else fallback
    except Exception as e:
        log_status(f"[titulo] Falha ao gerar título para {nome_arquivo}: {e}. Usando fallback.")
        return fallback
```
- Adicionar a constante `PROMPT_TITULO` encodando a convenção acima (junto do `PROMPT_QUALITATIVO`).
- Reusa `CLIENT`, `MODEL_NAME`, `log_status`, `Path`, `types` já importados no módulo.

---

## Tarefa 3 — Orquestrador (`scripts_v2/orquestrador.py`, `ingerir_documentos`)

Gerar o título no loop qualitativo (onde o markdown já existe) e gravá-lo nas duas tabelas:

1. Importar `gerar_titulo_documento` junto de `extrair_markdown_pdf` (nos dois blocos de import do topo).
2. No loop qualitativo ([348-389](scripts_v2/orquestrador.py#L348-L389)), após obter `markdown, modo`:
   ```python
   if modo == "placeholder":
       titulo = Path(nome).stem or nome      # sem conteúdo útil → usa o nome
   else:
       titulo = await _to_thread(gerar_titulo_documento, cnpj_norm, nome, markdown)

   await _to_thread(repo.salvar_compendio_qualitativo, cnpj_norm, nome, md5_arquivo, markdown, titulo, force)
   # Unifica: se este mesmo PDF também virou manifesto quantitativo, grava o título lá.
   await _to_thread(repo.definir_titulo_quantitativo, cnpj_norm, md5_arquivo, titulo)
   ```
   - `from pathlib import Path` já está importado no orquestrador.
   - Como a trilha quantitativa roda **antes** da qualitativa no mesmo `ingerir_documentos`, a linha do manifesto quantitativo (quando o arquivo é financeiro) já existe quando o `definir_titulo_quantitativo` é chamado → o update encontra a linha. Para arquivos não-financeiros, é no-op.

---

## Tarefa 4 — Repositório (`scripts_v2/servico_repositorio.py`)

1. **`salvar_compendio_qualitativo`** ([568](scripts_v2/servico_repositorio.py#L568)): adicionar parâmetro `titulo: str | None = None` e incluí-lo no `registro` do upsert.
2. **Nova `definir_titulo_quantitativo(cnpj, hash_md5, titulo)`**: `update emissor_compendio_quantitativo set titulo = ... where cnpj = ... and hash_md5 = ...`. (No-op silencioso se não houver linha.)
3. **`listar_compendios_qualitativos`** ([329](scripts_v2/servico_repositorio.py#L329)) e **`listar_compendios_quantitativos`** ([347](scripts_v2/servico_repositorio.py#L347)): incluir `titulo` no `.select(...)`.
4. **`montar_visao_completa_emissor`** ([398-411](scripts_v2/servico_repositorio.py#L398-L411)): no item de markdown,
   - `"titulo": item.get("titulo") or item.get("nome_arquivo") or "Documento"`,
   - manter `"origem": item.get("nome_arquivo")` (referência interna exibida em cinza).
   - Os itens de análise/delta seguem com seus títulos fixos atuais.
   - `compendios_quantitativos` já é retornado como vem do banco → agora inclui `titulo` automaticamente.

---

## Tarefa 5 — API
Nenhuma mudança. `GET /emissores/{cnpj}/visao-completa` retorna `dict` livre; os campos `titulo` fluem sozinhos no `markdowns` e em `compendios_quantitativos`.

---

## Tarefa 6 — Front

1. **`frontend/lib/types.ts`**: em `QuantitativeManifest`, adicionar `titulo?: string | null;`. (`MarkdownDocument.titulo` já existe — sem mudança.)
2. **`frontend/components/markdown-viewer.tsx`**: já renderiza `titulo` em destaque e `origem` (nome do arquivo) em cinza — **nenhuma mudança lógica**; passa a exibir o nome descritivo automaticamente. (Opcional: prefixar a linha cinza com "Arquivo: " para deixar claro que é a referência interna.)
3. **`frontend/app/detalhe-emissor/[identificador]/page.tsx`** — `manifestoColumns` ([103-123](frontend/app/detalhe-emissor/[identificador]/page.tsx#L103-L123)): na coluna "Arquivo", exibir `item.titulo || item.nome_arquivo` em destaque e, opcionalmente, `item.nome_arquivo` em uma segunda linha menor/cinza como referência.

---

## Verificação (end-to-end)

1. Rodar a migração SQL (Tarefa 1) no Supabase.
2. Subir API (`uvicorn api.main:app --port 8000`) e front (`npm run dev` em `frontend/`).
3. **Upload de uma demonstração financeira** → na lista de Markdowns, o item aparece com título tipo "Demonstrações Financeiras Dez2025" (e selo "financeiro"), com o nome do arquivo (UUID) em cinza como referência; o mesmo título aparece na tabela de manifesto quantitativo.
4. **Upload de uma escritura/rating** → título descritivo coerente ("Escritura 2ª Emissão VPLT" / "Rating ... Ago2022"); sem selo financeiro; sem linha no manifesto quantitativo.
5. **PDF sem conteúdo (placeholder)** → título = nome do arquivo (fallback), sem chamada LLM extra.
6. **Idempotência**: reenviar o mesmo PDF sem `force` → pulado (hash), sem regenerar título nem duplicar.
7. **Registros antigos** (forward-only): continuam exibindo o nome do arquivo como título até serem reenviados — comportamento esperado.
8. **Checagens**: AST parse de `orquestrador.py`/`servico_ia_qualitativa.py`/`servico_repositorio.py`; `tsc --noEmit` em `frontend/`.

## Fora de escopo
- Backfill dos registros existentes (decisão: forward-only).
- Renomear/normalizar `nome_arquivo` (ele permanece como referência interna, intacto).
- Mudanças na extração de markdown (Tarefa do plano `markdown-todos-pdfs.md`) ou na trilha quantitativa de dados.
