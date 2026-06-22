# HANDOVER — credit-data-dl V2

> Documento de transição entre conversas. O usuário (**Gabriel**, dono/arquiteto) continua a mesma linha de trabalho numa conversa nova, começando do zero. Eu (Claude) atuo como **Tech Lead / Arquiteto**: discuto, desenho e **entrego planos autocontidos** em `.claude/plans/`; o usuário **delega a implementação a agentes Codex** (em conversas paralelas). Não implemento código direto a menos que pedido. Idioma: **pt-BR**. Plataforma: **Windows** (PowerShell + Bash disponíveis).
>
> **Estado macro (2026-06-22):** backend (serviços + orquestrador + repositório + API FastAPI) **pronto e validado**; front Next.js **funcional e em polimento**. Em curso: (a) **refactor de estilo p/ a marca BOCAINA**, (b) **título descritivo de documentos**, (c) **fix de contraste do menu**. Passo 6 (análise de crédito por LLM) segue **por último, de propósito**.

---

## 1. O que é o projeto

`credit-data-dl`: pipeline de extração/consolidação de dados de **debêntures brasileiras** para análise de crédito corporativo. Semeadura por **ticker** (ex.: PETR26): descobre o emissor (CNPJ via ANBIMA), cruza com CVM, baixa dados de mercado e demonstrações, aceita **upload de PDFs processados por IA (Gemini)**, e consolida tudo num **Supabase (Postgres remoto)**.

Em **refactoring V2 ("SaaS & API-Ready")** na pasta `scripts_v2/`. O V1 (`scripts/`) é batch local, só referência.

**Stack:** Python async, Supabase/Postgres, Google Gemini (`gemini-2.5-flash`), pdfplumber/pypdf, Playwright, httpx; API FastAPI + uvicorn; Front Next.js 16 (App Router) + React 19 + Tailwind v4 + TypeScript.

---

## 2. Arquitetura (camadas)

```
Front (Next.js, BFF)  →  API (FastAPI)  →  orquestrador.py  →  serviços de coleta + servico_repositorio.py  →  Supabase
```

- **Serviços de coleta (puros):** `servico_identidade.py`, `servico_cvm.py`, `servico_mercado.py`, `servico_ia_quantitativa.py`, `servico_ia_qualitativa.py`. Recebem input, devolvem `dict`/`str`. **Não falam com banco.** PDFs nunca tocam disco — circulam como `bytes` em memória.
- **`servico_repositorio.py`:** **única** camada que conhece o Supabase (fronteira de portabilidade — trocar de banco = reescrever só este módulo). Síncrono; chamado via `asyncio.to_thread`.
- **`orquestrador.py`:** maestro. Sequencia serviços, faz "Peek Before Leap" (dedup por hash MD5), persiste via repositório, atualiza `pipeline_jobs`. Assíncrono. **Não cria jobs** — a API cria e passa `process_id`.
- **API FastAPI (`api/`):** fina, sobre o orquestrador. Cria job, dispara em background (`BackgroundTasks`), expõe leituras. Auth por `X-API-Key`.
- **Front Next.js (`frontend/`):** consome a API via **BFF** — o browser fala só com o Next.js, que injeta o `X-API-Key` server-side. A key **nunca** vai ao browser.
- **`servico_analise_credito.py` (POR ÚLTIMO):** Passo 6, análise de crédito por LLM. Deixado para o fim de propósito (validar antes que front→API→banco alimenta os dados certos). Usuário já tem prompts/estrutura prontos.

---

## 3. Decisões de arquitetura travadas (com o porquê)

| Decisão | Escolha | Porquê |
|---|---|---|
| Alvo de curto prazo | Ferramenta interna **mono-operador** | Sem multi-tenant/RLS agora; adicionar depois é migração aditiva. |
| Jobs longos | **BackgroundTasks + `pipeline_jobs`** (polling) | Pipeline leva minutos; request síncrona estouraria timeout. Sem Celery/Redis. |
| Portabilidade de banco | **Repositório é a única fronteira**; IDs gerados na app (`uuid.uuid4()`), nunca `gen_random_uuid()` | Permite trocar de banco. |
| Storage de demonstrações | **Linhas numéricas normalizadas** (não JSON) | Bom p/ gráficos/SQL. JSON é só read-model transitório p/ o LLM. |
| Pontos de entrada | **Dois:** `ingerir_ticker` e `ingerir_documentos` | Resolve chicken-egg (CNPJ antes dos PDFs). |
| Camada deep do mercado | **Desligada por padrão**, opt-in via flag | Calculadora ANBIMA raspa data-a-data (lenta). |
| Front → API | **BFF** (key só server-side) | Segredo nunca no browser; sem CORS no caminho normal; à prova de futuro fora do localhost. |
| `delta_markdown` (Passo 6) | **Gerado por LLM** | Diff narrativo capta significância. |

---

## 4. Schema (Supabase) — `scripts_v2/sql/supabase_schema_v2.sql`

Script **DROP + CREATE completo** (apaga dados). Tabelas: `emissores`, `demonstracoes_financeiras`, `deb_caracteristicas`, `deb_agenda`, `deb_historico_diario`, `emissor_compendio_qualitativo`, `emissor_compendio_quantitativo`, `emissor_analise_credito`, `pipeline_jobs`. Views: `v_ultimo_periodo`, `v_portfolio_ativo`, `v_proximos_pagamentos`, `v_ultima_analise_credito`, `v_emissor_debentures`, `v_jobs_recentes`.

**Gotchas:**
- `deb_agenda` UNIQUE = `NULLS NOT DISTINCT (ticker_deb, data_evento, evento, data_base)` (4 colunas).
- `emissor_compendio_qualitativo`: 1 linha por PDF (`markdown_conteudo`), UNIQUE `(cnpj, hash_md5)`.
- `emissor_compendio_quantitativo`: só manifesto (nome+hash); os números vão p/ `demonstracoes_financeiras`.
- `emissor_analise_credito`: **insert-only** (versionado, sem UNIQUE).
- `pipeline_jobs`: `id text` (UUID da app); `status` text livre (`pendente | rodando | concluido | concluido_com_erros | erro`); `etapa_atual`, `progresso` jsonb, `erro`. (No código, jobs são tratados como "processos"; `tipo="cadastro"`.)
- **Migração pendente (plano de títulos):** adicionar `titulo text` em `emissor_compendio_qualitativo` e `emissor_compendio_quantitativo` (ver §8c).

---

## 5. API FastAPI (`api/`) — PRONTA e validada

Camada fina sobre o orquestrador. Base `http://localhost:8000`; auth header `X-API-Key` (`/health` público). Arquivos: `api/{config,seguranca,esquemas,rotas_cadastro,rotas_leitura,main}.py`. `main.py` aplica `WindowsProactorEventLoopPolicy` (Playwright no Windows) e monta os routers com `Depends(exigir_api_key)`.

> ⚠️ **Atenção:** os endpoints foram **renomeados** de `/ingest/*` para `/cadastro/*` e as leituras foram **muito expandidas** desde o HANDOVER antigo. Lista canônica abaixo.

**Escrita (retornam `202` + `{process_id}`):**
- `POST /cadastro/ticker` — JSON `{ticker, deep?, data_corte_deep?}` → `repo.criar_processo("cadastro", ticker)` → background → `orquestrador.ingerir_ticker(..., process_id=...)`.
- `POST /cadastro/documentos` — multipart `cnpj` + `arquivos` (lê `UploadFile`→`bytes` em memória) → `repo.criar_processo("cadastro", cnpj)` → background → `ingerir_documentos(...)`.

**Leitura (em `rotas_leitura.py`):**
- `GET /processos` → `listar_processos_recentes` (view `v_jobs_recentes`); `GET /processos/{id}` (404 se inexistente).
- `GET /portfolio` (`v_portfolio_ativo`); `GET /agenda-eventos` (`v_proximos_pagamentos`).
- `GET /ativos?identificador=&resumo=` — resolve ticker/CNPJ/ticker_ação; `resumo=1` evita baixar agenda+histórico (caminho leve p/ dropdowns); usa `historico_limit`.
- `GET /ativos/opcoes?q=&limit=` — autocomplete (combobox).
- `GET /ativos/{ticker}/historico?offset=&limit=` — histórico diário paginado.
- `GET /emissores/resolver/{identificador}`; `GET /emissores/{cnpj}` → `{emissor, debentures}`; `GET /emissores/{cnpj}/visao-completa` → dossiê (emissor + debêntures + demonstrações + estruturadas + manifesto quant + **markdowns** + última análise).

**Limitação conhecida:** BackgroundTasks é in-process — reinício no meio deixa o job `rodando` (ok p/ mono-operador local).

---

## 6. `servico_repositorio.py` — referência (síncrono; chamar via `to_thread`)

Funções de **processos/jobs** (renomeadas de job→processo): `criar_processo(tipo, alvo)→id`, `atualizar_processo(id,*,status=,etapa_atual=,progresso=,erro=)`, `buscar_processo(id)→dict|None`, `listar_processos_recentes()`.

**Leitura:** `buscar_emissor`, `buscar_hashes_qualitativo/quantitativo(cnpj)→set`, `buscar_periodos_demonstracoes`, `buscar_datas_historico`, `buscar_ultima_analise`, `montar_demonstracoes_estruturadas(cnpj,*,rows=,emissor=)`, `listar_demonstracoes_financeiras`, `listar_compendios_qualitativos`, `listar_compendios_quantitativos`, `listar_detalhes_ativos(cnpj=None,*,incluir_series=True,historico_limit=)`, `montar_detalhe_ativo(ticker,*,historico_limit=)`, `buscar_ativo_por_ticker`, `buscar_opcoes_ativo_emissor(q,*,limit=)`, `listar_historico_ativo_paginado(ticker,*,offset=,limit=)`, `resolver_emissor_por_identificador`, `montar_visao_completa_emissor`, `listar_portfolio`, `listar_agenda_eventos`, `listar_debentures_emissor`.

**Escrita:** `salvar_emissor`, `salvar_caracteristicas`, `salvar_agenda`, `salvar_historico`, `periodos_para_linhas`, `salvar_demonstracoes`, `salvar_compendio_qualitativo(cnpj,nome,hash,markdown,force=False)`, `salvar_compendio_quantitativo(cnpj,nome,hash,force=False)`, `salvar_analise_credito`.

**Performance (já aplicada):** `listar_detalhes_ativos` reescrita p/ batching com `.in_(...)` (4 queries fixas, não 1+3N); `montar_visao_completa_emissor` paraleliza leituras independentes com `ThreadPoolExecutor` (supabase-py httpx é thread-safe) e reaproveita linhas; `IN_FILTER_SIZE`/`_chunks` helpers. Conexão: `_get_client()` lazy singleton; carrega `.env.local` e `.env`; exige `SUPABASE_URL` + `SUPABASE_KEY` (service_role).

---

## 7. Front Next.js (`frontend/`) — FUNCIONAL

App Router + TS + Tailwind v4 + React 19. **BFF**: `frontend/lib/api.ts` (`import "server-only"`) é a única fronteira com a key; `apiGet(path, {revalidate?})` usa Data Cache quando `revalidate` é setado, senão `cache:"no-store"`. Env: `frontend/.env.local` com `API_BASE_URL=http://localhost:8000` + `API_KEY=` (= a da API). `.env*` gitignored.

**Rotas reais** (≠ do HANDOVER antigo, que listava `/pagamentos`,`/emissores`,`/jobs`):
- `/` — Visão Geral / portfólio (`force-dynamic` p/ não pré-renderizar no build sem API).
- `/detalhe-ativo` — exige seleção via `AssetSelectorCombobox` (autocomplete `/ativos/opcoes`); histórico paginado.
- `/detalhe-emissor` (busca) e `/detalhe-emissor/[identificador]` — dossiê via `/visao-completa`.
- `/cadastro-dados` — forms de ticker e documentos + monitor de processo (polling) + processos recentes.
- Route Handlers (BFF): `app/api/processos/[id]`, `app/api/cadastro/documentos`, `app/api/detalhe-ativo/[ticker]/historico`, `app/api/detalhe-ativo/opcoes`. Escrita de ticker via Server Action (`app/cadastro-dados/actions.ts`).

**Bugs já corrigidos:** `redirect()` fora do try/catch (NEXT_REDIRECT); escopo de `cnpj` no upload; `formatPercent`; `error.tsx`.

**Tema da marca (em andamento):** `globals.css` já migrado p/ tokens BOCAINA (verde `#0a2300` / cream `#fff0dc`, chrome verde, tons semânticos, sombras esverdeadas, raios); `layout.tsx` usa **Gotham** local (`next/font/local`) + header verde com logo. Ver §8a. ⚠️ O header referencia `/brand/bocaina-logo-cream.png` — **garantir que o asset exista em `frontend/public/brand/`** (idealmente SVG).

---

## 8. Planos ativos em `.claude/plans/` (backlog atual)

### 8a. `front-estilo-bocaina.md` — redesign visual p/ a marca BOCAINA (EM ANDAMENTO pelo Codex)
Tema **claro + cromo verde**; **só Gotham** (sem serifada New York); **só logo+pássaro** (sem padronagens/22,5°). Tokens já no `globals.css`; falta varrer componentes (sombras, raios, glass removido, `text-white`→cream, `text-rose`→`--danger`), nav e assets de logo. Inspiração: site oficial https://bocainacapital.com/. Decisões salvas na memória `marca-bocaina.md`.

### 8b. `markdown-todos-pdfs.md` — todo PDF vira markdown salvo e visível ✅ IMPLEMENTADO E VERIFICADO (nesta conversa)
A trilha qualitativa já transcreve qualquer PDF em markdown; o bug era **descartar** quando o LLM retornava vazio. Implementado: `extrair_markdown_pdf()` (LLM +1 retry → texto bruto → placeholder; nunca vazio); orquestrador **sempre salva** (contadores `qual_fallback`/`qual_sem_conteudo`, sem descarte); repositório marca `financeiro` no item de markdown cruzando hashes do manifesto quant; front mostra selo "financeiro". **Verificado:** AST parse + `tsc` OK; falta só o teste end-to-end com PDFs reais. Recuperar antigos = reenviar (forward-only; bytes originais não são guardados).

### 8c. `titulos-descritivos-documentos.md` — título descritivo por documento (PLANEJADO, não implementado)
`nome_arquivo` (UUID) vira só referência interna; gerar título via LLM sobre o markdown ("ITR Mar2026", "Escritura 2ª Emissão VPLT"…). **Forward-only**; título gravado **nas duas tabelas** (qual+quant). Requer **ALTER TABLE … ADD COLUMN titulo text** (qual+quant), nova `gerar_titulo_documento()`, `definir_titulo_quantitativo()`, ajuste em `montar_visao_completa_emissor` e no front (`QuantitativeManifest.titulo` + coluna do manifesto). `MarkdownDocument.titulo` já existe.

### 8d. `fix-nav-contraste.md` — abas inativas verde-no-verde (PLANEJADO)
Diagnóstico: o `app-nav.tsx` **já usa texto cream nos inativos** (correto) → o sintoma é **build/cache defasado**. Plano: (1) apagar `frontend/.next` + restart dev (provável causa real); (2) blindar com tokens `--chrome-item-*` e a regra "inativo ⇒ texto `--chrome-ink` cream; nunca verde".

> Planos legados (já entregues): `servico_repositorio.md`, `orquestrador.md`, `correcao-orquestrador-jobs.md`, `api-fastapi.md`, `front-nextjs.md`.

---

## 9. Fluxo de processamento de um PDF (resumo de referência)

`POST /cadastro/documentos` → lê bytes → `criar_processo` (pendente) → 202 → background `ingerir_documentos`:
1. `validacao_emissor` (emissor precisa existir; senão job=`erro`).
2. `peek_hashes` (dedup por MD5, por trilha).
3. `ia_quant` — só arquivos financeiros (heurística de nome): Gemini→JSON CVM → `demonstracoes_financeiras` + manifesto quant.
4. `ia_qual` — **todos** os arquivos: Gemini→markdown fiel (modo Texto por lotes, fallback Vision); agora **sempre salva** (texto bruto/placeholder se falhar).
5. `finalizado` → `concluido` | `concluido_com_erros`.

Cada PDF passa pelas **duas trilhas** (financeiro = dados + markdown). Idempotência por hash, por trilha. Leitura posterior: `/emissores/{cnpj}/visao-completa` monta a lista de Markdowns (qual + análises), com selo `financeiro` quando o hash também está no manifesto quant.

---

## 10. Convenções do projeto

- **Planos em `.claude/plans/<nome-descritivo>.md`** (versionados no Git; `.claude/` não está no `.gitignore`). Links relativos. Assumir que o executor (Codex) não tem o histórico.
- **Memória** em `…/memory/`: `v2-arch-decisions.md`, `convencao-planos.md`, `api-fastapi-decisions.md`, `marca-bocaina.md`. Índice em `MEMORY.md`.
- **Env:** serviços carregam `.env.local` (GEMINI_API_KEY); repositório carrega `.env.local`+`.env` (SUPABASE_URL, SUPABASE_KEY service_role); API usa `API_KEY` (+ opcional `CORS_ORIGINS`); front `API_BASE_URL`+`API_KEY`. Tudo gitignored.
- Idioma **pt-BR**. Usuário **delega a Codex**; eu entrego planos. **Não revertam** mudanças que o Codex já fez em paralelo (verificar antes).

---

## 11. Como rodar / verificar

- Schema: rodar `scripts_v2/sql/supabase_schema_v2.sql` no SQL Editor do Supabase (DROP+CREATE). Migração de títulos (§8c): `ALTER TABLE … ADD COLUMN IF NOT EXISTS titulo text`.
- Orquestrador CLI: `python scripts_v2/orquestrador.py ticker PETR26` | `… docs <CNPJ> <pasta_pdfs>`.
- API: na raiz, `uvicorn api.main:app --port 8000` (precisa `.env.local`/`.env` com SUPABASE+GEMINI+`API_KEY`). Docs em `/docs`.
- Front: em `frontend/`, `npm run dev` (3000) ou `npm run build && npm run start`. `tsc`: `./node_modules/.bin/tsc --noEmit` (rodar de dentro de `frontend/`). Se o estilo "não pega": apagar `frontend/.next` e reiniciar.
- Validar: idempotência (rodar 2× não duplica); empresa Fechada (sem cod_cvm → CVM pulado sem quebrar); `API_KEY` não vaza no bundle do browser (devtools); chamadas do browser só p/ `:3000`.

---

## 12. Histórico desta conversa (o que rolou)

Ordem cronológica do que foi feito/decidido nesta sessão (para continuidade):

1. **Performance do front** diagnosticada e corrigida: N+1 em `/ativos` (batching), dossiê paralelizado (`ThreadPoolExecutor`), Data Cache (`revalidate`) no front, caminho `resumo=1`, `force-dynamic` em `/`. (Codex estendeu com histórico paginado, `/ativos/opcoes` e `AssetSelectorCombobox`.)
2. **Plano de estilo BOCAINA** (`front-estilo-bocaina.md`): revisei o front inteiro, li o Guia de Identidade (PDF) e o site oficial; decisões do dono: claro+cromo verde, só Gotham, só logo/pássaro. Memória `marca-bocaina.md` criada. Codex começou a aplicar (tokens já no `globals.css`/`layout.tsx`).
3. **Plano "markdown p/ todos os PDFs"** (`markdown-todos-pdfs.md`) — **implementado pelo Codex e verificado por mim** (extrair_markdown_pdf, sempre salvar, selo financeiro). Constatação-chave: a trilha qualitativa já é um transcritor genérico; o bug era o descarte por markdown vazio.
4. **Explicações** detalhadas do fluxo da API e de todas as etapas/desfechos por arquivo (a pedido do usuário).
5. **Plano de títulos descritivos** (`titulos-descritivos-documentos.md`): nome do arquivo só p/ referência interna; título por LLM; forward-only; nas duas tabelas. (Planejado, não implementado.)
6. **Plano de fix do menu** (`fix-nav-contraste.md`): abas inativas verde-no-verde — a fonte já está correta; causa provável = build defasado; blindar com tokens de chrome.
7. **Este HANDOVER** reescrito do zero refletindo o estado atual.

### Primeira ação sugerida na próxima conversa
1. Confirmar com o Codex o andamento de `front-estilo-bocaina.md` (8a) e `fix-nav-contraste.md` (8d); verificar o asset do logo em `frontend/public/brand/`.
2. Rodar o **teste end-to-end** do `markdown-todos-pdfs` (reenviar um PDF financeiro + um escaneado; conferir lista de Markdowns e selo "financeiro").
3. Encaminhar `titulos-descritivos-documentos.md` (8c) p/ implementação (lembrar do ALTER TABLE).
4. Só então: planejar/implementar o **Passo 6** (`servico_analise_credito.py`).
