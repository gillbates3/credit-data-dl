# HANDOVER — credit-data-dl V2 (continuação da arquitetura)

> Documento de transição entre conversas. O usuário (Gabriel, dono/arquiteto do projeto) continua a mesma linha de trabalho numa nova conversa. **Próximo passo: planejar a API FastAPI.** Eu (Claude) atuo como **Tech Lead / Arquiteto** — discuto e desenho, o usuário delega a implementação a agentes Codex. Não implemento código diretamente a menos que pedido; entrego **planos autocontidos**.

---

## 1. O que é o projeto

`credit-data-dl`: pipeline de extração/consolidação de dados de **debêntures brasileiras** para análise de crédito corporativo. Semeadura por **ticker** (ex.: PETR26): a partir do ticker, descobre o emissor (CNPJ via ANBIMA), cruza com CVM, baixa dados de mercado e demonstrações financeiras, aceita upload de PDFs processados por IA (Gemini), e consolida tudo num **Supabase (Postgres)**.

Está em **refactoring V2 ("SaaS & API-Ready")** na pasta `scripts_v2/`. O V1 (`scripts/`) é batch local e serve só de referência.

**Stack:** Python (async), Supabase/Postgres, Google Gemini (`gemini-2.5-flash`), pdfplumber, Playwright, httpx. Futuro front: Next.js. Plataforma: Windows (PowerShell + Bash disponíveis).

---

## 2. Arquitetura V2 (camadas)

```
Front (Next.js)  →  API (FastAPI)  →  orquestrador.py  →  serviços de coleta + servico_repositorio.py  →  Supabase
```

- **Serviços de coleta (puros, prontos):** `servico_identidade.py`, `servico_cvm.py`, `servico_mercado.py`, `servico_ia_quantitativa.py`, `servico_ia_qualitativa.py`. Recebem input, devolvem `dict`/`str`. **Não falam com banco.** PDFs nunca tocam disco — circulam como `bytes` em memória.
- **`servico_repositorio.py` (pronto):** única camada que conhece o Supabase. **Fronteira de portabilidade** — trocar de banco = reescrever só este módulo. Síncrono.
- **`orquestrador.py` (pronto, com correção pendente):** maestro. Sequencia serviços, aplica "Peek Before Leap" (dedup), persiste via repositório, atualiza `pipeline_jobs`. Assíncrono.
- **API FastAPI (PRÓXIMO):** fina, sobre o orquestrador. Cria job, dispara em background, expõe leituras.
- **`servico_analise_credito.py` (POR ÚLTIMO):** Passo 6, análise de crédito por LLM. **Deixado para o fim de propósito** — o usuário quer primeiro validar que o front→banco alimenta os dados corretamente; ele já tem prompts e estrutura de análise prontos.

---

## 3. Decisões de arquitetura travadas (com o porquê)

| Decisão | Escolha | Porquê |
|---|---|---|
| Alvo de curto prazo | **Ferramenta interna mono-operador** | Sem multi-tenant/RLS/coluna de tenant agora. Schema atual serve. Adicionar tenant depois é migração aditiva. |
| Execução de jobs longos | **FastAPI BackgroundTasks + tabela `pipeline_jobs`** | Pipeline leva minutos (Playwright+CVM+Gemini); request síncrona estoura timeout. API dispara em background, devolve `job_id`, front faz polling. Sem Celery/Redis. |
| `delta_markdown` da análise | **Gerado por LLM** (compara versão anterior + dados novos) | Diff narrativo capta significância; diff programático não. (Só relevante no Passo 6.) |
| Portabilidade de banco | **Repositório é a única fronteira**; IDs gerados na app (`uuid.uuid4()`), **nunca** `gen_random_uuid()` | Usuário pode trocar de banco no futuro. |
| Storage de demonstrações | **Linhas numéricas normalizadas** (não JSON) | Bom para gráficos/SQL. O JSON é só read-model transitório para o LLM (`montar_demonstracoes_estruturadas`). |
| Pontos de entrada do orquestrador | **Dois separados:** `ingerir_ticker` e `ingerir_documentos` | Resolve chicken-egg (precisa do CNPJ antes de associar PDFs). Mapeia para dois fluxos no front. |
| Camada deep do mercado | **Desligada por padrão**, opt-in via flag | Calculadora ANBIMA raspa data-a-data (lenta). Light é rápida e suficiente por padrão. |
| Atomicidade hash+números | **Por ordenação de escrita** (demonstrações antes do manifesto) | Sem transação multi-tabela nem função no banco (preserva portabilidade); idempotência cobre crash no meio. |

---

## 4. Schema (Supabase) — `scripts_v2/sql/supabase_schema_v2.sql`

Script **DROP + CREATE completo e idempotente**. Tabelas: `emissores`, `demonstracoes_financeiras`, `deb_caracteristicas`, `deb_agenda`, `deb_historico_diario`, `emissor_compendio_qualitativo`, `emissor_compendio_quantitativo`, `emissor_analise_credito`, `pipeline_jobs`. Views: `v_ultimo_periodo`, `v_portfolio_ativo`, `v_proximos_pagamentos`, `v_ultima_analise_credito`, `v_emissor_debentures`, `v_jobs_recentes`.

**Gotchas importantes:**
- `deb_agenda` UNIQUE = `NULLS NOT DISTINCT (ticker_deb, data_evento, evento, data_base)` — 4 colunas (V1 tinha 3). O `on_conflict` do repositório reflete isso.
- `emissor_compendio_qualitativo`: 1 linha por PDF (`markdown_conteudo`), UNIQUE `(cnpj, hash_md5)`.
- `emissor_compendio_quantitativo`: só manifesto (hashes); os números vão para `demonstracoes_financeiras`.
- `emissor_analise_credito`: **insert-only** (versionado, sem UNIQUE); `metadados` jsonb guarda `tickers_deb` etc.
- `pipeline_jobs`: `id text` = UUID gerado na app; `tipo` ∈ `ingestao|analise`; `status` text livre (sem CHECK) — valores: `pendente | rodando | concluido | concluido_com_erros | erro`; `etapa_atual`, `progresso` jsonb, `erro`.
- IDs das demais tabelas: `bigint GENERATED ALWAYS AS IDENTITY`.

---

## 5. Contratos exatos (referência canônica)

### Serviços de coleta

**Assíncronos (`await`):**
- `servico_identidade.buscar_identidade_emissor(ticker)` → `{"ticker","nome_emissor","cnpj_emissor"(só dígitos),"cod_cvm"|None,"categoria_cvm"|None,"tipo_capital":"Aberto"|"Fechado","status":"SUCESSO"|"ERRO"|...}`
- `servico_cvm.buscar_dados_cvm(cnpj, codigo_cvm, anos_retroativos=2)` → `{"cnpj","cod_cvm","periodos":{...}}`
- `servico_mercado.buscar_dados_mercado(ticker, deep=False, data_corte_deep=None, datas_desconhecidas=None)` → `{"ticker_deb","caracteristicas":{...sem cnpj/ticker...},"agenda":[...],"historico_diario":[...]}`

**Síncronos (via `asyncio.to_thread`):**
- `servico_ia_quantitativa.extrair_dados_quantitativos(cnpj, arquivos, periodos_existentes_db=None)` → `{"cnpj","periodos":{...},"processed_files":[{"nome_arquivo","hash_md5"}]}`. Auto-filtra não-financeiros.
- `servico_ia_qualitativa.extrair_dados_qualitativos(cnpj, arquivos, markdown_existente="", incluir_frontmatter=True)` → **string markdown**. NÃO filtra. Com `incluir_frontmatter=False` + 1 arquivo → só o corpo daquele arquivo.

`arquivos` = `list[tuple[str, bytes]]` = `(nome, conteudo_pdf)`. `periodos` (CVM e quant) têm formato **idêntico**: `{"YYYY-MM-DD":{"tipo":"DFP"|"ITR","demonstracoes":{"BPA":{"1":{"cd_conta","ds_conta","valor"}},"BPP","DRE","DFC","DVA"}}}`.

### `servico_repositorio.py` (síncrono — chamar via `to_thread`)
Leitura: `buscar_emissor(cnpj)`, `buscar_hashes_qualitativo(cnpj)→set`, `buscar_hashes_quantitativo(cnpj)→set`, `buscar_periodos_demonstracoes(cnpj)→set`, `buscar_datas_historico(ticker)→set`, `buscar_ultima_analise(cnpj)→dict|None`, `montar_demonstracoes_estruturadas(cnpj)→dict`.
Escrita: `salvar_emissor(identidade)`, `salvar_caracteristicas(cnpj,ticker,carac)`, `salvar_agenda(cnpj,ticker,agenda)→int`, `salvar_historico(ticker,hist)→int`, `periodos_para_linhas(cnpj,resultado)→list`, `salvar_demonstracoes(linhas)→int`, `salvar_compendio_qualitativo(cnpj,nome,hash,markdown,force=False)`, `salvar_compendio_quantitativo(cnpj,nome,hash,force=False)`, `salvar_analise_credito(cnpj,analise_md,delta_md,metadados)`.
Jobs: `criar_job(tipo,alvo)→job_id`, `atualizar_job(job_id,*,status=,etapa_atual=,progresso=,erro=)`, `buscar_job(job_id)→dict|None`.
Helpers expostos: `normaliza_cnpj(cnpj)`. Conexão: `_get_client()` lazy singleton; carrega `.env.local` depois `.env`; exige `SUPABASE_URL` + `SUPABASE_KEY` (service_role).

### `orquestrador.py` (assíncrono)
- `ingerir_ticker(ticker, *, deep=False, data_corte_deep=None, job_id=None) → dict` — P1 identidade → P2 CVM (só se `cod_cvm`) → P3 mercado. Retorna `{ticker,cnpj,tipo_capital,periodos_cvm,eventos_agenda,dias_historico,erros}`.
- `ingerir_documentos(cnpj, arquivos, *, force=False, job_id=None) → dict` — valida emissor existe → peek hashes → pré-filtra por md5 → P4a quant (demonstrações antes do manifesto) → P4b qual (1 arquivo por vez). Retorna `{cnpj,quant_processados,qual_processados,pulados_quant,pulados_qual,erros}`.
- **Não cria jobs** — só atualiza. A API cria o job e passa `job_id`.
- Roteamento de PDFs: a **mesma lista** vai para os dois serviços de IA; cada um se auto-seleciona; dedup independente por tabela de compêndio.

---

## 6. Estado atual (o que está feito / pendente)

- ✅ Schema V2 finalizado (com `pipeline_jobs` + `v_jobs_recentes`). **Precisa ter sido rodado no Supabase.**
- ✅ Os 5 serviços de coleta prontos (incluindo ajustes V2: `incluir_frontmatter` no qualitativo, `periodos_existentes_db` no quantitativo).
- ✅ `servico_repositorio.py` implementado pelo Codex e **revisado** — fiel ao plano, on_conflict corretos, smoke test ok.
- ✅ `orquestrador.py` implementado pelo Codex e **revisado** — fiel ao plano.
- ✅ Correção do orquestrador (`correcao-orquestrador-jobs.md`) **aplicada e confirmada** (2026-06-15): try/except de borda nos dois pontos de entrada, status `concluido_com_erros`, comentário do schema e premissa em `montar_demonstracoes`. As 4 mudanças verificadas no código.
- ✅ Plano da API FastAPI escrito em `.claude/plans/api-fastapi.md` (autocontido p/ Codex). Decisões travadas: auth por API key (`X-API-Key`); deploy a decidir (rodar local, BackgroundTasks in-process); pasta `api/` na raiz; job tipo `ingestao` com `alvo=cnpj` p/ documentos. Inclui helpers de leitura a adicionar no repositório (views).
- 🔜 **PRÓXIMO:** delegar o plano da API ao Codex e revisar a implementação. Depois: front Next.js e, por último, `servico_analise_credito.py` (Passo 6).

**Gap revisado (motivo da correção pendente):** exceções inesperadas (ex.: `salvar_emissor` lança `ValueError` se `nome_emissor` vazio; chamada não protegida em `ingerir_ticker`) deixavam o job preso em `rodando`, quebrando o modelo de polling.

---

## 7. PRÓXIMO PASSO — API FastAPI (meu plano mental, a refinar com o usuário)

Camada **fina** sobre o orquestrador. Desenho proposto:

**Endpoints de escrita (disparam pipeline):**
- `POST /ingest/ticker` (body: `{ticker, deep?, data_corte_deep?}`) → `repo.criar_job("ingestao", ticker)` → `BackgroundTasks` → `ingerir_ticker(..., job_id=...)` → retorna `{job_id}` na hora.
- `POST /ingest/documentos` (multipart: `cnpj` + arquivos) → ler `UploadFile` para `bytes` em memória (`await file.read()`, nunca disco) → `repo.criar_job("ingestao", cnpj)` → `BackgroundTasks` → `ingerir_documentos(cnpj, arquivos, job_id=...)` → `{job_id}`.

**Endpoints de leitura (polling + dados):**
- `GET /jobs/{job_id}` → `repo.buscar_job`. `GET /jobs` → `v_jobs_recentes`.
- `GET /portfolio` → `v_portfolio_ativo`; `GET /proximos-pagamentos` → `v_proximos_pagamentos`; `GET /emissores/{cnpj}` → emissor + `v_emissor_debentures`.

**Detalhes técnicos:**
- BackgroundTasks aceita funções async — roda o orquestrador no event loop. Após o fix, exceções já marcam o job `erro`, então o front vê pela polling mesmo que o endpoint já tenha retornado.
- Config: carregar `.env.local`/`.env` (SUPABASE + GEMINI). CORS para o Next.js.
- O front nunca segura a service_role key — só fala com a API. (Por isso leituras via API, não Supabase direto.)

**Decisões a resolver com o usuário antes de finalizar o plano da API (perguntar):**
1. **Autenticação:** nenhuma (local), uma API key única no header (mono-operador), ou Supabase Auth? (Recomendação provável: API key única — mono-operador.)
2. **Deploy/hospedagem:** onde a API Python vai rodar? (Vercel não roda Python facilmente; opções: Railway/Render/Fly/local.) Afeta a viabilidade de BackgroundTasks (são in-process: se o processo reinicia no meio, o job fica `rodando`; aceitável para ferramenta local/mono-operador — anotar como limitação conhecida).
3. **Estrutura de pastas da API:** dentro de `scripts_v2/` (ex.: `scripts_v2/api/`) ou um novo módulo/pasta (`api/`, `backend/`)? Confirmar convenção.
4. **`tipo` do job para documentos:** o schema só permite `ingestao|analise`. Documentos é parte de `ingestao` (alvo=cnpj). Confirmar se quer um `tipo` distinto (exigiria ampliar o schema).

---

## 8. Convenções do projeto (importante manter)

- **Planos/artefatos de delegação vão em `.claude/plans/<nome-descritivo>.md`** no projeto (versionados no Git — `.claude/` NÃO está no `.gitignore`). Nome descritivo, não o slug do harness. Links relativos (`../../`) para arquivos do repo. Já existem: `servico_repositorio.md`, `orquestrador.md`, `correcao-orquestrador-jobs.md`, e este `HANDOVER.md`.
- **Chaves de ambiente:** serviços V2 carregam `.env.local` (GEMINI_API_KEY); repositório carrega `.env.local` e `.env` (SUPABASE_URL, SUPABASE_KEY service_role). `.env*` está no `.gitignore`.
- O usuário **delega implementação a agentes Codex**; minha entrega são planos/prompts autocontidos (assumir que o executor não tem o histórico desta conversa).
- Idioma: **português (pt-BR)**.

---

## 9. Memória do projeto (auto-carregada na próxima sessão)

Arquivos em `.../memory/`: `v2-arch-decisions.md` (decisões travadas), `convencao-planos.md` (onde salvar planos). Índice em `MEMORY.md`. Vale criar uma memória nova quando a API for decidida.

---

## 10. Como rodar / verificar (referência rápida)

- Schema: rodar `scripts_v2/sql/supabase_schema_v2.sql` no SQL Editor do Supabase (DROP+CREATE — apaga dados).
- Smoke test repositório: `python scripts_v2/servico_repositorio.py` (precisa de `.env.local`/`.env` com chaves Supabase).
- Orquestrador CLI: `python scripts_v2/orquestrador.py ticker PETR26` | `python scripts_v2/orquestrador.py docs <CNPJ> <pasta_pdfs>`.
- Testar idempotência (rodar 2×, nada duplica) e empresa Fechada (sem cod_cvm → CVM pulado sem quebrar).

---

### Primeira ação sugerida na próxima conversa
1. Confirmar se a correção do orquestrador (`correcao-orquestrador-jobs.md`) foi aplicada pelo Codex.
2. Fazer as 4 perguntas da seção 7 ao usuário.
3. Escrever o plano autocontido da API em `.claude/plans/api-fastapi.md`.
