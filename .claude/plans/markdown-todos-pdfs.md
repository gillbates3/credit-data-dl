# Plano: Markdown para TODOS os PDFs ingeridos (sem exceção)

> **Entrega:** spec autocontido para um agente executor (Codex). Assuma que ele **não** tem o histórico desta conversa. Idioma do projeto: **pt-BR**. Plataforma: **Windows**.

## Context

Hoje, ao subir documentos (`ingerir_documentos`), cada PDF passa por **duas trilhas independentes**:
- **Quantitativa** ([servico_ia_quantitativa.py](scripts_v2/servico_ia_quantitativa.py)): extrai demonstrações no padrão CVM → popula `demonstracoes_financeiras` + grava manifesto (só nome+hash) em `emissor_compendio_quantitativo`. Pula por nome arquivos claramente não-financeiros (`is_financial_pdf_name`).
- **Qualitativa** ([servico_ia_qualitativa.py](scripts_v2/servico_ia_qualitativa.py)): o `PROMPT_QUALITATIVO` é um **transcritor genérico de PDF → markdown fiel** (cobre demonstrações financeiras, rating, releases, escrituras…). Salva o markdown em `emissor_compendio_qualitativo`.

A lista de "Markdowns" do front é montada **apenas** a partir de `emissor_compendio_qualitativo` + análises ([servico_repositorio.py:392](scripts_v2/servico_repositorio.py#L392)), renderizada em [detalhe-emissor/[identificador]/page.tsx:327](frontend/app/detalhe-emissor/[identificador]/page.tsx#L327).

**O problema:** quando a extração qualitativa retorna markdown vazio (PDF escaneado, falha transitória do Gemini, sanitização agressiva), o orquestrador **descarta** o arquivo em vez de salvá-lo ([orquestrador.py:354-369](scripts_v2/orquestrador.py#L354-L369)) — ele incrementa `pulados_qual`, loga "Markdown vazio" e **não grava linha nenhuma**. Resultado: o PDF some da lista de Markdowns (caso real: `PASN12`, arquivo `e87d…` entrou só como quantitativo com `quant_processados=1`, `qual_processados=0`).

**Objetivo:** garantir que **todo PDF ingerido vire um markdown salvo e visível** na lista de Markdowns (no mesmo formato dos qualitativos atuais), **mantendo intacta** a população do banco de demonstrações financeiras. Não é preciso mudar a trilha quantitativa nem o schema — a trilha qualitativa já é o "PDF → markdown" desejado; basta torná-la **robusta (nunca descartar)** e, no front, **sinalizar quais markdowns também viraram dados financeiros**.

## Decisões travadas (definidas pelo dono do produto)

| Decisão | Escolha |
|---|---|
| Fallback quando o LLM falhar/retornar vazio | **Robusto**: tenta LLM (com 1 retry) → se vazio, salva o **texto bruto** extraído do PDF como markdown → se nem isso, salva um **markdown-placeholder com aviso**. Nunca descarta. |
| PDFs já ingeridos sem markdown (ex.: `e87d…` do PASN12) | **Corrigir daqui pra frente.** Os bytes originais não são persistidos (só hash+markdown), então recuperar antigos = **reenviar os mesmos PDFs** (o hash não está no qualitativo → serão reprocessados). Documentar, sem migração automática. |
| Distinção na UI | **Sim, badge "financeiro"**: cruzar os hashes de `emissor_compendio_quantitativo` e marcar no item de markdown quando o mesmo PDF também gerou demonstrações. |

## Princípio que NÃO muda
- Trilha quantitativa (`extrair_dados_quantitativos` → `salvar_demonstracoes`) e o manifesto quantitativo permanecem como estão. O banco financeiro continua sendo populado normalmente.
- `servico_repositorio.py` continua sendo a **única** fronteira do Supabase.
- Idempotência por hash MD5 por trilha (constraints `uq_qualitativo_cnpj_hash` / `uq_quantitativo_cnpj_hash`) permanece.
- **Sem mudança de schema SQL.** O badge "financeiro" é computado por interseção de hashes em tempo de leitura.

---

## Tarefa 1 — `servico_ia_qualitativa.py`: extrator por arquivo que nunca retorna vazio

Hoje o corpo do loop em `extrair_dados_qualitativos` decide modo texto-por-lotes vs vision-por-lotes e monta o bloco markdown. Extrair essa lógica e expor um primitivo por-arquivo.

1. **Extrair helper** `_gerar_markdown_llm(config, cnpj, nome_arquivo, conteudo_em_bytes) -> str | None` com a lógica atual (detecção de scanned via pdfplumber → `processar_pdf_texto_por_lotes` → fallback `processar_pdf_vision_por_lotes` → `montar_bloco_markdown`). Refatorar o loop de `extrair_dados_qualitativos` para usar esse helper (mantém o comportamento atual e o uso pelo CLI/standalone).

2. **Nova função pública** `extrair_markdown_pdf(cnpj, nome_arquivo, conteudo_em_bytes) -> tuple[str, str]` retornando `(markdown, modo)` com `modo ∈ {"llm", "texto_bruto", "placeholder"}`, garantindo conteúdo não-vazio:
   ```
   markdown = _gerar_markdown_llm(...)           # 1ª tentativa
   if not markdown: markdown = _gerar_markdown_llm(...)   # 1 retry (cobre falhas transitórias do Gemini)
   if markdown: return markdown, "llm"
   # Fallback 1: texto bruto extraído do PDF (reusa extract_full_text_from_bytes)
   texto, _ = extract_full_text_from_bytes(conteudo_em_bytes, nome_arquivo)
   if texto.strip():
       return f"# {nome_arquivo}\n\n> _Transcrição automática (texto bruto; o extrator estruturado não retornou markdown)._\n\n{texto}", "texto_bruto"
   # Fallback 2: placeholder com aviso
   return f"# {nome_arquivo}\n\n> _Não foi possível extrair conteúdo textual deste PDF (provável PDF escaneado sem OCR ou falha do extrator). Reenvie com `force` para reprocessar._", "placeholder"
   ```
   - O formato do markdown (`# {nome_arquivo}\n\n…`) deve casar com o que hoje é gravado (o `montar_bloco_markdown` já produz `# {nome}\n\n{conteudo}`).

---

## Tarefa 2 — `orquestrador.py` `ingerir_documentos`: nunca descartar no qualitativo

Reescrever o loop qualitativo ([linhas 337-381](scripts_v2/orquestrador.py#L337-L381)):

1. Adicionar contadores ao `progresso` inicial: `"qual_fallback": 0` (texto bruto) e `"qual_sem_conteudo": 0` (placeholder).
2. Para cada `(nome, conteudo)` em `novos_qual`:
   ```
   md5_arquivo = _md5(conteudo)
   try:
       markdown, modo = await _to_thread(extrair_markdown_pdf, cnpj_norm, nome, conteudo)
       await _to_thread(repo.salvar_compendio_qualitativo, cnpj_norm, nome, md5_arquivo, markdown, force)
       progresso["qual_processados"] += 1
       if modo == "texto_bruto":
           progresso["qual_fallback"] += 1
           _append_erro(progresso, f"Markdown via texto bruto (LLM não retornou estruturado) para {nome}.")
       elif modo == "placeholder":
           progresso["qual_sem_conteudo"] += 1
           _append_erro(progresso, f"PDF sem texto extraível; salvo placeholder para {nome}.")
   except Exception as exc:
       progresso["pulados_qual"] += 1
       _append_erro(progresso, f"Falha no qualitativo para o arquivo {nome}: {exc}")
   ```
   - **Remover** o `if markdown.strip(): … else: pulados_qual += 1` antigo. Agora só conta `pulados_qual` em exceção real de I/O/DB (não por conteúdo vazio).
   - Manter o `_atualizar_processo(...)` por arquivo (feedback ao vivo).
3. Importar `extrair_markdown_pdf` junto dos demais imports do serviço qualitativo (nos dois blocos try/except de import no topo).

> Efeito: todo PDF novo gera linha em `emissor_compendio_qualitativo` → aparece na lista de Markdowns. Falha de extração vira `concluido_com_erros` (com aviso no `progresso.erros`), mas o arquivo **continua presente** (com texto bruto ou placeholder).

---

## Tarefa 3 — `servico_repositorio.py`: marcar markdown que também é financeiro

Em `montar_visao_completa_emissor` ([linha 392](scripts_v2/servico_repositorio.py#L392)), já carregamos `compendios_quantitativos` (têm `hash_md5`) e `compendios_qualitativos` (têm `hash_md5`).

1. Antes do loop de markdowns, montar `hashes_quant = {c["hash_md5"] for c in compendios_quantitativos if c.get("hash_md5")}`.
2. Ao montar cada item qualitativo, adicionar `"financeiro": item.get("hash_md5") in hashes_quant`.
3. Itens de análise/delta recebem `"financeiro": False`.

Nenhuma outra mudança no repositório. (A interseção é por hash, precisa; nenhum custo extra de query — os dois conjuntos já são buscados.)

---

## Tarefa 4 — API (`api/rotas_leitura.py`)

`GET /emissores/{cnpj}/visao-completa` já retorna `dict[str, object]` livre e repassa `markdowns` como vêm do repositório. O novo campo `financeiro` flui **automaticamente** — **nenhuma mudança de código** na rota. (Confirmar apenas que não há modelo Pydantic restringindo o shape; hoje não há.)

---

## Tarefa 5 — Front

1. **`frontend/lib/types.ts`** — adicionar campo opcional em `MarkdownDocument`:
   ```ts
   export interface MarkdownDocument {
     id: string;
     tipo: "qualitativo" | "analise_credito" | "delta_analise";
     titulo: string;
     origem?: string | null;
     hash_md5?: string | null;
     financeiro?: boolean;   // mesmo PDF também gerou demonstrações financeiras
     criado_em?: string | null;
     conteudo: string;
   }
   ```
2. **`frontend/components/markdown-viewer.tsx`** — ao lado do `StatusBadge` do `tipo` (no botão da lista, ~linha 53), renderizar um selo "financeiro" quando `document.financeiro`:
   ```tsx
   {document.financeiro ? (
     <span className="inline-flex items-center rounded-full border border-[var(--info-line)] bg-[var(--info-bg)] px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--info)]">
       financeiro
     </span>
   ) : null}
   ```
   (Usa os tokens semânticos da marca já presentes no `globals.css`.) Opcionalmente mostrar o mesmo selo no cabeçalho do painel de conteúdo selecionado.
3. **`frontend/lib/process-monitor.ts`** — em `formatProgressLabel`, adicionar rótulos amigáveis para os novos contadores `qual_fallback` ("Qualitativos via texto bruto") e `qual_sem_conteudo` ("Qualitativos sem conteúdo"). O monitor já renderiza contadores genericamente, então isso é só cosmético.

> A tabela de "manifesto quantitativo" no detalhe do emissor permanece (indica quais PDFs alimentaram o DB financeiro). Com o fix, esses mesmos PDFs também aparecem na lista de Markdowns, agora com o selo "financeiro".

---

## Verificação (end-to-end)

1. Subir API (`uvicorn api.main:app --port 8000`) e front (`npm run dev` em `frontend/`).
2. **Reenviar** um PDF de demonstração financeira (ex.: o `e87d…` do PASN12) em `/cadastro-dados`:
   - Job conclui `concluido` (ou `concluido_com_erros` se houve fallback); `qual_processados ≥ 1`.
   - Em `/detalhe-emissor/PASN12`, o PDF aparece na lista de **Markdowns** com conteúdo **e** selo **"financeiro"**.
   - As **demonstrações financeiras** continuam populadas (tabela financeira + manifesto quantitativo inalterados).
3. **PDF escaneado/sem texto**: aparece na lista com o **placeholder de aviso** (não some); job vira `concluido_com_erros` com mensagem em `progresso.erros`.
4. **PDF não-financeiro** (ex.: escritura): aparece como markdown (sem selo "financeiro"); **não** entra em `demonstracoes_financeiras` (quant pula por nome) — comportamento correto.
5. **Idempotência**: reenviar o mesmo PDF sem `force` → pulado no qualitativo (hash já existe), sem duplicar. Com `force` → reprocessa e atualiza.
6. **Python**: `python -c "import ast; ast.parse(open('scripts_v2/orquestrador.py').read()); ast.parse(open('scripts_v2/servico_ia_qualitativa.py').read())"` sem erro; `tsc --noEmit` em `frontend/` limpo.

## Fora de escopo
- Mudanças na trilha quantitativa, no schema SQL, ou em `demonstracoes_financeiras`.
- Persistir os bytes originais dos PDFs (backfill automático fica inviável por isso; recuperação = reenvio manual).
- Análise de crédito (Passo 6).
