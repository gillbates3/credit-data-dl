# Plano: Front Next.js (V2) — slice vertical sobre a API FastAPI

> Prompt autocontido para um agente executor (Codex). **Assuma que você não tem o histórico da conversa que gerou este plano.** Idioma do projeto: **pt-BR**. Plataforma: Windows (PowerShell + Bash disponíveis). A API é fina e já está pronta — o front consome os endpoints existentes; **não** altere `api/`, `scripts_v2/` nem o schema.

## Status atual / handover (2026-06-16)

### O que já foi implementado

- O `frontend/` foi criado e está funcional com **Next.js 16.2.2 + App Router + TypeScript + Tailwind**.
- Existe um BFF server-side central em `frontend/lib/api.ts` com `import "server-only"`. A `API_KEY` continua apenas server-side.
- Layout raiz, navegação e páginas principais prontas:
  - `/`
  - `/pagamentos`
  - `/emissores`
  - `/emissores/[cnpj]`
  - `/ingestao`
  - `/jobs`
  - `/jobs/[id]`
  - `/dossie`
  - `/dossie/[identificador]`
- Polling de jobs implementado via `frontend/app/api/jobs/[id]/route.ts`.
- Formulários de ingestão implementados com **Server Actions**.
- Busca por **CNPJ ou ticker** já foi adicionada nos fluxos de:
  - consulta de emissor
  - dossiê
  - upload de documentos
- Existe uma tela nova de **dossiê do emissor** com:
  - card cadastral do emissor
  - tabela de debêntures
  - tabela filtrável de demonstrações financeiras
  - visualizador de markdowns
  - lista de manifestos quantitativos

### Correções já feitas no front

- Corrigido o bug do `redirect()` engolido por `try/catch` nas Server Actions de ingestão.
- Corrigido `frontend/app/ingestao/actions.ts` para o upload por documentos montar `FormData` corretamente e resolver o `cnpj` apenas dentro do `try`.
- Criado `frontend/app/error.tsx` para erros amigáveis de leitura quando a API estiver fora do ar ou responder com 5xx.
- `formatPercent()` em `frontend/lib/format.ts` foi ajustado para **não** usar heurística por magnitude; hoje ele formata o valor de forma direta como percentual.
- O resumo de `/` foi ajustado para calcular **próximo vencimento futuro** (não a menor data absoluta).
- Dependências do `frontend/package.json` foram fixadas com versões concretas, compatíveis com React 19.2.x.
- `frontend/tsconfig.json` foi ajustado para não depender de escrita de `tsbuildinfo` no `npx tsc --noEmit`.
- Upload por Server Action estava falhando com `Body exceeded 1 MB limit`; isso foi corrigido em `frontend/next.config.ts` via `experimental.serverActions.bodySizeLimit = "20mb"`.

### Validação já feita

- `npx tsc --noEmit` passa.
- `npm run build` passa.
- O front já renderizou e respondeu corretamente nas rotas principais durante smoke tests locais.
- Foi validado que `frontend/lib/api.ts` é o único local com `process.env.API_KEY`; não há `NEXT_PUBLIC_` relacionado à API key.

### Desvio importante em relação ao plano original

O plano original dizia para **não alterar** `api/`, `scripts_v2/` nem o schema. Isso **não** se manteve 100%:

- Houve alterações em `api/rotas_leitura.py`.
- Houve alterações em `scripts_v2/servico_repositorio.py`.

Motivo: foi necessário suportar no produto a resolução **ticker <-> CNPJ** e expor um **dossiê completo do emissor** para o front.

### Endpoints/leituras extras adicionados para suportar o front atual

Foram adicionadas leituras extras no backend:

- `GET /emissores/resolver/{identificador}`
  - resolve `CNPJ`, `ticker_deb` ou `ticker_acao` para emissor/CNPJ
- `GET /emissores/{cnpj}/dossie`
  - retorna:
    - `emissor`
    - `debentures`
    - `demonstracoes_financeiras`
    - `demonstracoes_estruturadas`
    - `compendios_quantitativos`
    - `markdowns`
    - `ultima_analise_credito`

No repositório (`scripts_v2/servico_repositorio.py`) foram adicionadas funções para:

- resolver emissor por identificador
- listar demonstrações financeiras
- listar compêndios qualitativos
- listar compêndios quantitativos
- montar o dossiê do emissor

### Estado conhecido dos dados

- Para o caso real testado com `VPLT12`, a resolução `ticker_deb -> cnpj` funciona.
- O dossiê do emissor responde corretamente.
- Porém, para `VPLT12`, o retorno observado tinha:
  - debênture presente
  - emissor presente
  - **sem** `demonstracoes_financeiras`
  - **sem** `markdowns`
  - **sem** `compendios_quantitativos`
- Isso parece consistente com a base atual: ingestão de ticker populou emissor/debênture, mas ainda não havia PDFs quantitativos/qualitativos persistidos para esse emissor.

### Pontos de atenção para o próximo agente

- Se testar upload de PDFs, **reiniciar o `next dev`** depois de mudanças em `next.config.ts`; o aumento do `bodySizeLimit` só vale após restart.
- O fluxo de upload continua em **Server Action**. Se os PDFs reais crescerem além do limite configurado, considerar migrar o upload de documentos para um **Route Handler** BFF.
- O `app/error.tsx` hoje é global para o App Router; se necessário, pode valer separar boundaries por segmento no futuro.
- O front já aceita **ticker** em vários lugares, mas a consistência desse padrão ainda pode ser expandida/revisada nas próximas melhorias.
- O visualizador de markdown hoje usa `pre/whitespace-pre-wrap`; não há renderer Markdown rico.

### Arquivos principais tocados até aqui

- `frontend/app/layout.tsx`
- `frontend/app/page.tsx`
- `frontend/app/pagamentos/page.tsx`
- `frontend/app/emissores/page.tsx`
- `frontend/app/emissores/[cnpj]/page.tsx`
- `frontend/app/ingestao/page.tsx`
- `frontend/app/ingestao/actions.ts`
- `frontend/app/jobs/page.tsx`
- `frontend/app/jobs/[id]/page.tsx`
- `frontend/app/api/jobs/[id]/route.ts`
- `frontend/app/dossie/page.tsx`
- `frontend/app/dossie/[identificador]/page.tsx`
- `frontend/app/error.tsx`
- `frontend/components/*` (nav, tabelas, badges, formulários, markdown viewer, etc.)
- `frontend/lib/*`
- `frontend/next.config.ts`
- `frontend/package.json`
- `frontend/tsconfig.json`
- `api/rotas_leitura.py`
- `scripts_v2/servico_repositorio.py`

### Situação atual recomendada para continuidade

Partir do pressuposto de que:

- o slice vertical inicial do front já existe;
- o próximo trabalho é **melhoria incremental** do front;
- backend e front já divergem um pouco do plano original por causa do suporte a ticker e dossiê;
- o plano abaixo ainda serve como referência arquitetural, mas **não** reflete sozinho o estado atual do código.

## Context

A API FastAPI V2 (`api/`) está **implementada, testada e validada** — cobre ingestão (ticker + upload de PDFs em background com jobs em `pipeline_jobs`) e leitura (portfólio, próximos pagamentos, emissor+debêntures, jobs). O backend está completo até este ponto; o que falta antes do Passo 6 (análise de crédito por LLM, deixado por último de propósito) é o **front Next.js**, cujo objetivo declarado é **validar end-to-end que o fluxo front → API → banco alimenta os dados corretamente**.

## Decisões travadas (não reabrir)

| Decisão | Escolha | Porquê |
|---|---|---|
| Padrão de chamadas | **BFF** (Backend-for-Frontend) | A API exige `X-API-Key` (segredo). O browser fala **só** com o próprio Next.js (Server Components / Server Actions / Route Handlers), que injetam a key server-side. A key **nunca** vai ao browser. Bônus: chamadas servidor→servidor não disparam CORS. À prova de futuro quando a API sair do localhost. |
| Escopo | **Slice vertical completo** | Todas as telas dos endpoints atuais, validando escrita e leitura de ponta a ponta. |
| Acabamento | **Funcional e limpo** | Dashboard utilitário com Tailwind; foco em dados e fluxo, não em estética. |
| Estrutura | Pasta **`frontend/`** na raiz (ao lado de `api/` e `scripts_v2/`) | Monorepo simples. |

## Stack

- **Next.js (App Router, versão estável atual) + TypeScript**, criado com `create-next-app` em `frontend/`.
- **Tailwind CSS** para estilo (incluso no scaffolding do create-next-app).
- Sem libs de data-fetching client (React Query etc.) nesta fatia: leituras via Server Components; polling via `fetch` em client component contra Route Handler. Manter dependências mínimas.

## Contrato da API (referência — já implementada em `api/`)

Base: `http://localhost:8000`. Auth: header `X-API-Key`. `/health` é público.

**Escrita (retornam `202` + `{ "job_id": "<uuid>" }`):**
- `POST /ingest/ticker` — JSON `{ ticker: string, deep?: boolean, data_corte_deep?: string|null }`.
- `POST /ingest/documentos` — multipart: campo `cnpj` (string) + `arquivos` (1+ PDFs).

**Leitura:**
- `GET /jobs` → lista (view `v_jobs_recentes`, até 100).
- `GET /jobs/{job_id}` → job único (`404` se inexistente).
- `GET /portfolio` → lista (view `v_portfolio_ativo`).
- `GET /proximos-pagamentos` → lista (view `v_proximos_pagamentos`).
- `GET /emissores/{cnpj}` → `{ emissor: {...}, debentures: [...] }` (`404` se emissor inexistente).

**Job** (`v_jobs_recentes`): `{ id, tipo, alvo, status, etapa_atual, progresso (jsonb), erro, criado_em, atualizado_em }`. `status` ∈ `pendente | rodando | concluido | concluido_com_erros | erro`. `progresso` traz contadores (`periodos_cvm`, `eventos_agenda`, `dias_historico`, `quant_processados`, `qual_processados`, `pulados_*`) e `erros: string[]`. O front deve **parar o polling** quando `status` ∈ `{concluido, concluido_com_erros, erro}`.

Colunas das views (derivar tipos TS daqui; ver `../../scripts_v2/sql/supabase_schema_v2.sql`):
- **Portfólio** (`v_portfolio_ativo`): `ticker_deb, nome_emissor, grupo_economico, setor, tipo_capital, tipo, data_emissao, data_vencimento, volume_emissao, indexador, spread_emissao, especie, rating_emissao, agencia_rating, perspectiva_rating, lei_incentivo, agente_fiduciario, status`.
- **Próximos pagamentos** (`v_proximos_pagamentos`): `data_evento, ticker_deb, emissor, grupo_economico, evento, evento_arc, taxa, valor, status, dias_para_evento`.
- **Emissor → debêntures** (`v_emissor_debentures`): `cnpj, nome, grupo_economico, tipo_capital, ticker_deb, status, indexador, spread_emissao, data_vencimento, rating_emissao, agencia_rating, lei_incentivo`.
- **Emissor** (tabela `emissores`): `cnpj, cod_cvm, nome, categoria_cvm, tipo_capital, ticker_acao, grupo_economico, setor, observacao, criado_em, atualizado_em`.

## Config / ambiente

`frontend/.env.local` (não comitar — `.env*` já está no `.gitignore`), **sem** prefixo `NEXT_PUBLIC_` (tudo server-side):
```
API_BASE_URL=http://localhost:8000
API_KEY=<mesmo valor da API_KEY da API Python>
```
Criar também `frontend/.env.example` com as chaves vazias (esse pode comitar).

## `frontend/lib/api.ts` — única fronteira com a API (a key vive só aqui)

Helper server-side usado por Server Components, Server Actions e Route Handlers. Centraliza base URL + `X-API-Key`.
```ts
const BASE = process.env.API_BASE_URL!;
const KEY = process.env.API_KEY!;

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "X-API-Key": KEY },
    cache: "no-store",            // dados sempre frescos
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json() as Promise<T>;
}

export async function apiPostJson<T>(path: string, body: unknown): Promise<T> { /* idem, method POST, Content-Type json */ }
export async function apiPostForm<T>(path: string, form: FormData): Promise<T> { /* method POST, repassa FormData; NÃO setar Content-Type manualmente */ }
```
`ApiError` carrega `status` e mensagem para as telas tratarem `404`/erros. **Nunca** importar/usar este módulo em código client (`"use client"`) — só em Server Components, Server Actions e Route Handlers.

## Rotas e telas (App Router em `frontend/app/`)

Layout raiz com navegação (topbar ou sidebar simples): Portfólio · Próximos Pagamentos · Ingestão · Jobs.

1. **`/` — Dashboard / Portfólio** (Server Component): `apiGet("/portfolio")` → tabela com colunas principais (ticker, emissor, indexador, spread, vencimento, rating, status). *Obs.:* a view de portfólio não traz `cnpj`, então o detalhe de emissor é acessado pela tela própria (item 3), não por link direto da linha.
2. **`/pagamentos` — Próximos pagamentos** (Server Component): `apiGet("/proximos-pagamentos")` → tabela ordenada por `data_evento`, com badge para `dias_para_evento` (ex.: vermelho se ≤ 7).
3. **`/emissores` + `/emissores/[cnpj]` — Emissor** (Server Component): `/emissores` tem um campo de busca por CNPJ que navega para `/emissores/[cnpj]`. O detalhe chama `apiGet("/emissores/{cnpj}")` → card com dados do emissor + tabela das debêntures. Tratar `404` com mensagem amigável.
4. **`/ingestao` — Ingestão** (Client Components + Server Actions):
   - **Form ticker:** input ticker + checkbox `deep` (+ `data_corte_deep` opcional, condicional ao deep). Submit → Server Action chama `apiPostJson("/ingest/ticker", ...)` → recebe `job_id` → redireciona para `/jobs/[id]`.
   - **Form documentos:** input CNPJ + `<input type="file" multiple accept="application/pdf">`. Submit → Server Action repassa o `FormData` (campo `cnpj` + `arquivos`) via `apiPostForm("/ingest/documentos", form)` → `job_id` → redireciona para `/jobs/[id]`.
5. **`/jobs` — Lista de jobs** (Server Component): `apiGet("/jobs")` → tabela (alvo, tipo, status badge, etapa_atual, atualizado_em). Linha → `/jobs/[id]`.
6. **`/jobs/[id]` — Detalhe do job com polling ao vivo** (Client Component): faz polling de `/api/jobs/[id]` (Route Handler BFF) a cada ~2s; mostra `status`, `etapa_atual`, contadores de `progresso` e lista `progresso.erros`. **Para o polling** quando o status é terminal. Estados de loading/erro tratados.

## Route Handlers (BFF para o que o browser chama dinamicamente)

- **`frontend/app/api/jobs/[id]/route.ts`** (GET): proxy server-side de `apiGet("/jobs/{id}")` — usado pelo polling do client. Mantém a key fora do browser. Repassar `404`.
- (Opcional) **`frontend/app/api/jobs/route.ts`** (GET) se quiser auto-refresh client da lista; caso contrário a lista é Server Component com refresh manual.

As **escritas** usam **Server Actions** (não Route Handlers) — forms com `action={serverAction}`; Server Actions lidam nativamente com `FormData`/arquivos.

## Componentes compartilhados (`frontend/components/`)

- `StatusBadge` — mapeia `status` de job (`pendente|rodando|concluido|concluido_com_erros|erro`) e de debênture (`ativo` etc.) para cores Tailwind.
- `DataTable` simples (cabeçalho + linhas) ou tabelas locais por tela — manter leve.
- Formatadores: datas (`pt-BR`), moeda/volume (`Intl.NumberFormat`), percentuais para spread/taxa.

## Design (funcional e limpo)

Tailwind, paleta neutra (cinza/branco) com acento para ações primárias e cores semânticas nos badges. Layout responsivo básico, tabelas legíveis, formulários com validação client mínima e feedback de submit (disabled + spinner). Sem biblioteca de UI pesada; pode usar utilitários simples. Prioridade: clareza dos dados e do estado dos jobs.

## Verificação (end-to-end)

1. Subir a API: na raiz do repo, `uvicorn api.main:app --reload --port 8000` (precisa de `.env.local`/`.env` com SUPABASE/GEMINI/`API_KEY`).
2. Subir o front: em `frontend/`, `npm install` e `npm run dev` (porta 3000); `frontend/.env.local` com `API_BASE_URL` e `API_KEY` iguais aos da API.
3. **Ingestão ticker:** em `/ingestao`, submeter `PETR26` → redireciona para `/jobs/[id]` → status progride `rodando` → `concluido`/`concluido_com_erros`; o polling para sozinho.
4. **Ticker inválido** → job termina `erro` (não fica preso em `rodando`); a mensagem aparece em `progresso.erros`/`erro`.
5. **Upload de PDFs:** submeter CNPJ + PDFs → job processa quant/qual; CNPJ inexistente → job `erro` com "emissor inexistente; rode ingerir_ticker primeiro".
6. **Leituras:** `/` mostra portfólio; `/pagamentos` lista eventos; `/emissores/<cnpj>` mostra emissor + debêntures; `/jobs` lista os jobs.
7. **Segurança:** confirmar (devtools → Network/Sources) que `API_KEY` **não** aparece em nenhum bundle/response do browser; as chamadas do browser vão só para `localhost:3000` (Next), nunca direto para `:8000`.

## Fora de escopo (não fazer agora)

- Passo 6 / análise de crédito (telas e serviço) — virá depois.
- Autenticação de usuário no front (login). A `API_KEY` server-side basta para mono-operador.
- Gráficos de demonstrações financeiras / séries históricas (a API ainda não expõe esses read-models; fica para uma fatia futura).
- React Query, libs de UI pesadas, testes E2E automatizados.
- Decisão de deploy do front (roda local por enquanto).
