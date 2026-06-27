# HANDOVER — credit-data-dl V2

> Documento de transição entre conversas. O usuário (**Gabriel**, dono/arquiteto) continua a mesma linha de trabalho numa conversa nova, começando do zero. Eu (Claude) atuo como **Tech Lead / Arquiteto**: discuto, desenho e **entrego planos autocontidos** em `.claude/plans/`; o usuário **delega a implementação a agentes Codex** (em conversas paralelas). Não implemento código direto a menos que pedido. Idioma: **pt-BR**. Plataforma: **Windows** (PowerShell + Bash disponíveis).
>
> **Estado macro (2026-06-27):** backend (serviços + orquestrador + repositório + API FastAPI) **pronto e validado**; front Next.js **funcional**. **Estilo BOCAINA (8a) e fix de contraste do nav (8d) já estão code-complete**. Backlog atual de planos (prontos p/ o Codex): **humanizar rótulos de processo (8e)**, **stepper de etapas estilo metrô (8f)**, **aba "Gerenciar Dados" / CRUD da base (8g)**. **Novo workstream (esta sessão): acelerar a ingestão de PDFs (§8j)** — estudo empírico de modelos concluído (decisão: **migrar de gemini-2.5-flash → gemini-3.1-flash-lite**, com pendências) e **paralelismo de chunks** a desenhar. Decisão estratégica: **MarkItDown** (Office→markdown) **adiado**; **Batch API adiado** (dono não trabalha nisso agora). Passo 6 (análise de crédito por LLM) segue **por último, de propósito**.

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

### 8a. `front-estilo-bocaina.md` — redesign visual p/ a marca BOCAINA ✅ CODE-COMPLETE (verificado nesta sessão)
Tema **claro + cromo verde**; **só Gotham** (sem serifada New York); **só logo+pássaro** (sem padronagens/22,5°). Tokens já no `globals.css`; falta varrer componentes (sombras, raios, glass removido, `text-white`→cream, `text-rose`→`--danger`), nav e assets de logo. Inspiração: site oficial https://bocainacapital.com/. Decisões salvas na memória `marca-bocaina.md`.

### 8b. `markdown-todos-pdfs.md` — todo PDF vira markdown salvo e visível ✅ IMPLEMENTADO E VERIFICADO (nesta conversa)
A trilha qualitativa já transcreve qualquer PDF em markdown; o bug era **descartar** quando o LLM retornava vazio. Implementado: `extrair_markdown_pdf()` (LLM +1 retry → texto bruto → placeholder; nunca vazio); orquestrador **sempre salva** (contadores `qual_fallback`/`qual_sem_conteudo`, sem descarte); repositório marca `financeiro` no item de markdown cruzando hashes do manifesto quant; front mostra selo "financeiro". **Verificado:** AST parse + `tsc` OK; falta só o teste end-to-end com PDFs reais. Recuperar antigos = reenviar (forward-only; bytes originais não são guardados).

### 8c. `titulos-descritivos-documentos.md` — título descritivo por documento (PLANEJADO, não implementado)
`nome_arquivo` (UUID) vira só referência interna; gerar título via LLM sobre o markdown ("ITR Mar2026", "Escritura 2ª Emissão VPLT"…). **Forward-only**; título gravado **nas duas tabelas** (qual+quant). Requer **ALTER TABLE … ADD COLUMN titulo text** (qual+quant), nova `gerar_titulo_documento()`, `definir_titulo_quantitativo()`, ajuste em `montar_visao_completa_emissor` e no front (`QuantitativeManifest.titulo` + coluna do manifesto). `MarkdownDocument.titulo` já existe.

### 8d. `fix-nav-contraste.md` — abas inativas verde-no-verde ✅ CODE-COMPLETE (verificado nesta sessão)
Tokens `--chrome-item-*` no `globals.css`, nav legível (inativos em cream). Pequena divergência aceita: o `app-nav.tsx` usa `text-chrome-muted` + `bg-black/10` em vez dos tokens `--chrome-item-*` (que ficaram órfãos) — legível, passa contraste. Resta só **QA visual** rodando o app.

### 8e. `humanizar-rotulos-processo.md` — rótulos de processo (tipo/etapa/desfecho) (PARCIALMENTE no working tree; falta concluir)
Apresentação no front: `formatRotulo` (sentence-case + acrônimos cvm→CVM) p/ `tipo`/`etapa`; `rotuloEtapaProcesso` traduz etapa para ação descritiva ("Identificando emissor na ANBIMA") e mostra **desfecho** ("Concluído"/"Falhou") quando terminal. **Inclui Tarefa 2b: remover a coluna "Etapa atual" da tabela de processos recentes** (virou eco do Status). Helpers em `format.ts` já existem no working tree; faltam 2 call sites + a remoção da coluna (seção de reconciliação no plano detalha).

### 8f. `stepper-etapas-processo.md` — stepper visual de etapas estilo metrô (PLANEJADO)
Régua horizontal de progresso no rodapé do card esquerdo do monitor; nomes curtos de estação; estados concluida/pulada/atual/falhou/pendente derivados de `passos_concluidos`+`etapa_atual`+`status` (sem backend). Trata CVM pulada (empresa Fechada) e erro. `computarEtapas()` em `lib/process-monitor.ts` + componente `process-stepper.tsx`.

### 8g. `aba-gerenciar-dados.md` — nova aba CRUD da base por entidade (PLANEJADO)
Aba "Gerenciar Dados" (`/gerenciar-dados`) p/ visualizar e editar a base **sem** abrir o Supabase. Por debênture (características/agenda/histórico) e por emissor (DFs/qualitativo/quantitativo), + tabelas mestras de emissores/emissões. Decisões do dono: **CRUD célula a célula**; **hard delete com cascata** (impacto + 1 clique); **editar conteúdo de markdown**; confirmação simples sem auditoria; **reprocessamento sobrescrevendo edições manuais é aceito** (sem proteção sticky). ⚠️ FKs **sem `ON DELETE CASCADE`** → cascata explícita e ordenada no repositório (ordem no plano). Camadas: repo (`atualizar_/criar_/deletar_`) → API `/edicao` (PATCH/POST/DELETE) → front BFF.

### 8h. MarkItDown (Office→markdown) — INVESTIGADO, ADIADO (sem plano de execução ainda)
Avaliado nesta sessão: **não** substituir o Gemini na trilha qualitativa (Gemini é interpretativo: reestrutura tabelas, pula boilerplate, OCR; MarkItDown-core ≈ nosso fallback de texto bruto). **Decisão do dono:** ampliar para arquivos Office **só depois** da ingestão de PDFs estar 100% debugada/implementada. Viabilidade já confirmada (encaixe limpo via dispatcher por tipo na cabeça da trilha qual; o resto do fluxo é agnóstico a formato). Para docs financeiros tabela-pesados, **Docling/PyMuPDF4LLM** são alternativas melhores que o MarkItDown — avaliar num piloto quando for a hora.

### 8i. Status granular ao vivo — `progresso.mensagem_andamento` ✅ BACKEND JÁ IMPLEMENTADO (working tree, não commitado)
`servico_ia_qualitativa.py` e `servico_ia_quantitativa.py` agora aceitam um `status_callback` (helper `_emit_status`) que emite mensagens humanas finas durante o processamento (ex.: "Enviando páginas 1 a 8 ao Gemini", "Aguardando resposta do Gemini…", "PDF escaneado detectado…"). O `orquestrador.py` conecta isso via `notificar` e grava em **`progresso.mensagem_andamento`** (texto livre, atualizado a cada sub-passo). Também ganhou retry 429/503/UNAVAILABLE (3 tentativas) em `call_ai_with_text` nas duas trilhas.
> ⚠️ **Impacto nos planos 8e/8f (escritos ANTES deste campo existir — contemplar na implementação):** há agora um sinal **mais rico e já legível** que o enum `etapa_atual`. O card "ETAPA ATUAL" (8e) pode exibir `progresso.mensagem_andamento` (texto fino) em vez de/junto com o rótulo do enum; o stepper (8f) pode usar essa mensagem como legenda da estação ativa. O enum `etapa_atual` continua válido para a etapa "grossa".

### 8j. Acelerar a ingestão de PDFs — estudo de modelos + paralelismo (EM ANDAMENTO, esta sessão)
Motivação do dono: carga inicial de **centenas de emissores** (20-30 PDFs cada, alguns de 80-100 págs) é impraticável no fluxo sequencial atual. Plano do estudo: `.claude/plans/comparar-modelos-extracao.md`. Artefatos descartáveis: `tmp/comparar_modelos_extracao.py` (harness instrumentado: roda qual+quant nos 2 modelos, captura `finish_reason`/tokens/latência/custo, flags `--apenas-modelo/--thinking/--reforco/--tag/--dry-run`) e `tmp/probe_latencia.py` (mede TTFT vs geração). Saídas em `tmp/comparacao_modelos/`.

**Diagnóstico de latência (provado):** cada chunk de 8 págs leva ~30-40s, e **~89% é geração de output** (TTFT ~4s; ~150-260 tok/s; cada chunk gera ~6-9K tokens de markdown). Logo: chunk maior **não** acelera (mais output) e **arrisca truncar**; **paralelismo é a alavanca** (chunks são independentes). O harness é **sequencial de propósito** (mede o baseline = produção atual); o paralelismo ainda **não** foi implementado.

**Limites Gemini do dono (console, tier pago):** 2.5 Flash = **1.000 RPM / 1M TPM / 10K RPD**; 3.1 Flash-Lite = **150K RPD** (15x); 2.5 Flash-Lite = RPD ilimitado. **O gargalo da carga fria é o RPD** (chunking multiplica requisições): a 10K/dia ≈ ~50 emissores/dia; a 150K ≈ ~750/dia. RPM/TPM têm folga gigante (paralelismo é trivialmente seguro). **Preços (USD/1M, in/out):** 2.5 Flash $0,30/$2,50; 3.1 Flash-Lite $0,25/$1,50; 2.5 Flash-Lite $0,10/$0,40.

**Estudo de fidelidade (2.5 Flash vs 3.1 Flash-Lite, corpus Arteris/Regis Bittencourt — `Relatorio Anual 2025.pdf` 80p + `Relatorio Anual e Demonstracoes Financeiras.pdf` 75p):**
- 3.1 **thinking-off** → **resume demais** (cobre só ~45% dos números do 2.5; qual gerou 1/5 do conteúdo; quant 80 vs 218 contas). **Reprova** a regra de ouro "NÃO RESUMA".
- 3.1 **thinking-on (`-1`) + reforço de prompt anti-resumo** → **paridade de fidelidade**: cobre **97-98%** dos números do 2.5 (e às vezes mais); quant arq.1 = 204 vs 218 contas. Custo cai ~30% e latência empata (thinking conta como output e come a vantagem de velocidade).
- ⚠️ **Risco descoberto:** thinking **dinâmico** na quant (JSON) **trunca** — num arquivo o modelo gastou ~63K tokens raciocinando e estourou `MAX_TOKENS` → 0 contas. **Quant precisa de thinking com TETO FIXO (ex.: ~3.072) + `max_output_tokens` alto.**

**Decisões travadas:** (1) migrar p/ **gemini-3.1-flash-lite** (prêmio real = 15x RPD + ~30% mais barato, fidelidade equivalente); (2) **manter 8 págs/chunk** (dono); (3) **thinking-on na qual, thinking-limitado na quant**; (4) **reforço de prompt anti-resumo é necessário**; (5) Batch API e chunks maiores **fora de escopo** agora.
**Pendências antes de implementar:** (a) **micro-teste da quant** (thinking fixo + `max_output_tokens`) p/ confirmar fim do truncamento — **não rodado ainda**; (b) decidir se mantém **2.5 Flash como fallback configurável** (3.1 é **preview** = risco de estabilidade) — **indeciso**; (c) decidir **mecanismo de concorrência** p/ o paralelismo (**cliente async nativo** vs **ThreadPoolExecutor**) — **adiado**; (d) escrever o **plano do paralelismo** (semáforo global + backoff **com jitter** — 503/overload do 2.5 foi frequente nos testes). Troca em produção quando aprovado: `MODEL_NAME` em `servico_ia_qualitativa.py:60` + 2 strings inline em `servico_ia_quantitativa.py:266` e `:349` → unificar em `GEMINI_MODEL`/env.

> Planos legados (já entregues): `servico_repositorio.md`, `orquestrador.md`, `correcao-orquestrador-jobs.md`, `api-fastapi.md`, `front-nextjs.md`. Planos já implementados: `markdown-todos-pdfs.md` (8b), `front-estilo-bocaina.md` (8a), `fix-nav-contraste.md` (8d).

---

## 9. Fluxo de processamento de um PDF (resumo de referência)

`POST /cadastro/documentos` → lê bytes → `criar_processo` (pendente) → 202 → background `ingerir_documentos`:
1. `validacao_emissor` (emissor precisa existir; senão job=`erro`).
2. `peek_hashes` (dedup por MD5, por trilha).
3. `ia_quant` — só arquivos financeiros (heurística de nome): Gemini→JSON CVM → `demonstracoes_financeiras` + manifesto quant.
4. `ia_qual` — **todos** os arquivos: Gemini→markdown fiel — **PDF digital ⇒ modo Texto por lotes (8 pág.); PDF escaneado ⇒ modo Vision por lotes (15 pág.)**. A rota é decidida por `is_scanned`; Vision **não** é fallback de falha de texto — **isto é POR DESIGN (não reintroduzir):** falha no modo texto costuma ser erro transitório do Gemini (429/503), tratado pelos retries; não faz sentido gastar Vision num PDF que comprovadamente tem texto. **O mesmo vale na trilha quantitativa** (texto que falha não cai mais para Vision). Retries 429/503/UNAVAILABLE (3 tentativas). Sanitização do sufixo do tempfile (`re.match(r"^(\.[a-zA-Z0-9]+)")`) corrige `UnicodeEncodeError` no Windows. Agora **sempre salva** (texto bruto/placeholder se falhar).
5. `finalizado` → `concluido` | `concluido_com_erros`.

Cada PDF passa pelas **duas trilhas** (financeiro = dados + markdown). Idempotência por hash, por trilha. Durante o processamento, cada sub-passo emite status humano via `status_callback` → grava em `progresso.mensagem_andamento` (ver §8i). Leitura posterior: `/emissores/{cnpj}/visao-completa` monta a lista de Markdowns (qual + análises), com selo `financeiro` quando o hash também está no manifesto quant.

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

Ordem cronológica do que foi feito/decidido nesta sessão (2026-06-23 a 06-25):

1. **Auditoria de 8a/8d**: confirmei que o estilo BOCAINA e o fix de contraste do nav estão **code-complete** (greps de regressão limpos — sem teal/slate/glass/`text-white`; tokens no `globals.css`; assets de logo presentes em `frontend/public/brand/`). Resta só QA visual rodando o app.
2. **Dúvidas respondidas**: STATUS do portfólio sempre "ativo" porque a view `v_portfolio_ativo` filtra `WHERE status='ativo'` (valores possíveis: ativo|resgatado|vencido|default); significado de cada etapa do pipeline (ticker: identidade→cvm→mercado; documentos: validacao_emissor→peek_hashes→ia_quant→ia_qual→finalizado).
3. **Plano `humanizar-rotulos-processo.md` (8e)**: capitalização de enums (`formatRotulo`) + rótulos de ação descritivos com desfecho (`rotuloEtapaProcesso`) + **remoção da coluna "Etapa atual"** da tabela de recentes (redundante com Status). Helpers já no working tree; faltam 2 call sites + a remoção (reconciliação no plano).
4. **Plano `stepper-etapas-processo.md` (8f)**: stepper horizontal estilo metrô no monitor (decisões do dono: horizontal, nomes curtos).
5. **MarkItDown (8h)**: avaliado a fundo; viabilidade de Office confirmada (encaixe via dispatcher por tipo); **adiado** por decisão do dono até a ingestão de PDFs estar estável.
6. **Plano `aba-gerenciar-dados.md` (8g)**: nova aba CRUD da base por entidade (4 decisões do dono travadas; cascata explícita por falta de `ON DELETE CASCADE`).
7. **Este HANDOVER** atualizado (§8 backlog + macro state + este histórico).

> Working tree atual: edições parciais de 8e em `frontend/lib/format.ts` (helpers `formatRotulo`/`rotuloEtapaProcesso`) e em alguns call sites (`process-monitor-client`, `recent-processes-table`, `page`, `asset-detail-panel`). Tudo passa `tsc --noEmit`. Não revertido. **Novos arquivos desta sessão (não commitados):** `tmp/comparar_modelos_extracao.py`, `tmp/probe_latencia.py`, `tmp/comparacao_modelos/` (saídas), `.claude/plans/comparar-modelos-extracao.md`.

### Sessão 2026-06-26/27 (o que rolou)
1. Dono levantou: ingestão de PDFs lenta/impraticável p/ centenas de emissores. Explorada arquitetura (paralelismo, Batch, RPD) → §8j.
2. **Estudo de modelos completo** (2.5 Flash vs 3.1 Flash-Lite): harness instrumentado + 3 rodadas (3.1 thinking-off, 3.1 thinking-on+reforço, baseline 2.5). **Veredito: migrar p/ 3.1 Flash-Lite** (paridade de fidelidade com thinking-on+reforço; 15x RPD; ~30% mais barato). Detalhes/pendências em §8j.
3. Provado que a latência por chunk é **output-bound** (~89% geração) → paralelismo é a alavanca; chunk maior não ajuda.
4. HANDOVER atualizado (§8j + macro state + este histórico).

### Primeira ação sugerida na próxima conversa
1. **(Ingestão §8j)** Rodar o **micro-teste da quant** (3.1, thinking fixo ~3.072 + `max_output_tokens` alto) p/ confirmar fim do truncamento; decidir fallback 2.5 (preview) e mecanismo de concorrência; **escrever o plano do paralelismo** (semáforo global + backoff com jitter) e a migração `GEMINI_MODEL`.
2. Entregar ao Codex os planos prontos: **8e**, **8f**, **8g**.
3. Fechar o **QA visual** do estilo BOCAINA (8a/8d) rodando o app.
4. `titulos-descritivos-documentos.md` (8c) pendente (lembrar do ALTER TABLE).
5. Quando a ingestão estiver estável: **piloto MarkItDown/Docling** (8h) e, por último de propósito, **Passo 6** (`servico_analise_credito.py`).
