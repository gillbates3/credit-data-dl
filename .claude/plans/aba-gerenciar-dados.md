# Plano: Aba "Gerenciar Dados" — CRUD da base por entidade

> Spec autocontido para o agente executor (Codex). Assuma que ele **não** tem o histórico desta conversa. Idioma: **pt-BR**. Plataforma: **Windows**. Stack: Python async + Supabase/Postgres; API FastAPI; Front Next.js 16 (App Router) + React 19 + Tailwind v4 (tema BOCAINA).

## Context

Hoje, para corrigir ou limpar dados subidos errado (um **markdown enviado por engano**, **demonstrações financeiras erradas**, um campo de cadastro incorreto), o operador precisaria abrir o **Supabase direto** e mexer nas tabelas — com toda a complexidade de chaves e relações. Queremos uma **aba no próprio sistema** que permita **visualizar e editar a base de forma organizada por entidade de negócio** (debênture/ticker e emissor), **sem expor tabelas cruas**. Esta é a interface oficial de limpeza/ajuste/edição da base.

**Não** é um editor de tabelas SQL: o usuário escolhe um ticker ou um emissor e edita as informações associadas a ele; e há tabelas mestras de emissores e emissões para incluir/alterar/deletar.

### Decisões travadas (definidas pelo dono — não reabrir)

| Tema | Decisão |
|---|---|
| Granularidade | **CRUD completo célula a célula** em todas as tabelas (inclui histórico diário e cada conta das DFs). |
| Deleção de pai (emissor/debênture) | **Hard delete com cascata** (apaga de verdade os filhos), mostrando o **impacto** (contagens) antes, com **confirmação simples (1 clique)**. |
| Markdowns/qualitativo | **Editar conteúdo** (editor de markdown) + editar **título** + **deletar**. |
| Proteção | **Confirmação simples (1 clique)**, **sem** trilha de auditoria. |

## Arquitetura — onde figura

Mantém as camadas atuais e o princípio **"`servico_repositorio.py` é a única fronteira de banco"** (nenhum SQL no front/API):

```
Front (/gerenciar-dados) → BFF route handlers (injeta X-API-Key) → API (router novo de edição) → servico_repositorio (funções novas atualizar_/criar_/deletar_) → Supabase
```

- **Nav**: novo item **"Gerenciar Dados"** em [app-nav.tsx](frontend/components/app-nav.tsx) → rota `/gerenciar-dados`.
- **Auth**: igual ao resto (BFF + `X-API-Key`); a key nunca vai ao browser.

## Modelo de navegação da aba (3 seções)

1. **Por debênture (ticker)** — seletor de ticker (reusar [entity-selector-combobox.tsx](frontend/components/entity-selector-combobox.tsx)) → edita:
   - **Características** da debênture (form de campos).
   - **Agenda** de eventos (tabela editável célula a célula: editar/criar/deletar linha).
   - **Histórico diário** (tabela editável paginada — reusar o padrão de paginação já existente).
2. **Por emissor (CNPJ)** — seletor de emissor → edita:
   - **Dados do emissor** (form).
   - **Demonstrações financeiras** (tabela editável por linha/conta; deletar **período inteiro** em lote).
   - **Compêndios qualitativos** (lista: editar **título** e **conteúdo markdown**, **deletar**).
   - **Manifesto quantitativo** (lista: editar título, **deletar**).
3. **Tabelas mestras** — visão de **todos os emissores** e **todas as emissões**: **incluir** (create manual), **alterar** (inline) e **deletar** (cascata com impacto). Para edição profunda, linka para a seção 1/2 da entidade.

## Schema — relações e chaves (referência)

Origem: `scripts_v2/sql/supabase_schema_v2.sql`. PKs e FKs relevantes:
- `emissores(cnpj PK)`.
- `deb_caracteristicas(id PK, cnpj FK→emissores, ticker_deb UNIQUE)`.
- `deb_agenda(id PK, ticker_deb FK→deb_caracteristicas, cnpj FK→emissores)`.
- `deb_historico_diario(id PK, ticker_deb FK→deb_caracteristicas)`.
- `demonstracoes_financeiras(id PK, cnpj FK→emissores)`.
- `emissor_compendio_qualitativo(id PK, cnpj FK→emissores, UNIQUE(cnpj,hash_md5))`.
- `emissor_compendio_quantitativo(id PK, cnpj FK→emissores, UNIQUE(cnpj,hash_md5))`.
- `emissor_analise_credito(id PK, cnpj FK→emissores)`.

> **Crítico:** as FKs são `REFERENCES` **sem `ON DELETE CASCADE`**. Portanto a deleção em cascata **precisa ser explícita e ordenada no repositório** (deletar filhos antes do pai). Toda tabela tem `id` (ou `cnpj`) estável para endereçar linhas em UPDATE/DELETE.

## Tarefa A — `servico_repositorio.py` (novas funções)

Seguir os padrões existentes (`_get_client()`, `to_thread` na chamada). Adicionar famílias `atualizar_`/`criar_`/`deletar_`. **Whitelist de campos editáveis por tabela**; **chaves read-only** (`cnpj`, `ticker_deb`, `id`, `hash_md5` não são alteráveis por update genérico).

- **Emissores**: `listar_todos_emissores()`, `atualizar_emissor(cnpj, campos: dict)`, `criar_emissor_manual(campos)`, `deletar_emissor(cnpj)` (cascata — ver ordem abaixo), `contar_dependencias_emissor(cnpj)→dict` (p/ o preview de impacto).
- **Debêntures**: `listar_todas_debentures()`, `atualizar_caracteristicas(ticker, campos)`, `criar_debenture_manual(cnpj, campos)`, `deletar_debenture(ticker)` (cascata), `contar_dependencias_debenture(ticker)→dict`.
- **Agenda**: `atualizar_evento_agenda(id, campos)`, `criar_evento_agenda(ticker, cnpj, campos)`, `deletar_evento_agenda(id)`.
- **Histórico**: `atualizar_historico(id, campos)`, `deletar_historico(id)`, `criar_historico(ticker, campos)` (opcional).
- **Demonstrações**: `atualizar_demonstracao(id, campos)`, `deletar_demonstracao(id)`, `deletar_demonstracoes_periodo(cnpj, data_ref)`.
- **Qualitativo**: `atualizar_compendio_qualitativo(id, *, titulo=None, markdown=None)`, `deletar_compendio_qualitativo(id)`.
- **Quantitativo**: `atualizar_compendio_quantitativo(id, *, titulo=None)`, `deletar_compendio_quantitativo(id)`.
- **Análise de crédito** (opcional): `deletar_analise(id)`.

### Ordem da cascata (explícita)
- `deletar_debenture(ticker)`: **historico → agenda → deb_caracteristicas**.
- `deletar_emissor(cnpj)`: para cada ticker do emissor → **historico → agenda**; depois **deb_caracteristicas → demonstracoes_financeiras → compendio_qualitativo → compendio_quantitativo → emissor_analise_credito → emissores**.

Reaproveitar leituras já existentes (`listar_detalhes_ativos`, `montar_visao_completa_emissor`, `listar_debentures_emissor`, `listar_historico_ativo_paginado`, `listar_compendios_*`) para popular as telas — sem duplicar.

## Tarefa B — API (`api/rotas_edicao.py`, novo router)

Router fino com `prefix="/edicao"`, `Depends(exigir_api_key)`, montado em `api/main.py`. Schemas de payload (parciais) em `api/esquemas.py`. Endpoints REST:

- Emissores: `GET /edicao/emissores` · `POST /edicao/emissores` · `PATCH /edicao/emissores/{cnpj}` · `GET /edicao/emissores/{cnpj}/impacto-delecao` · `DELETE /edicao/emissores/{cnpj}`.
- Debêntures: `GET /edicao/debentures` · `POST /edicao/debentures` · `PATCH /edicao/debentures/{ticker}` · `GET /edicao/debentures/{ticker}/impacto-delecao` · `DELETE /edicao/debentures/{ticker}`.
- Agenda: `POST /edicao/debentures/{ticker}/agenda` · `PATCH /edicao/agenda/{id}` · `DELETE /edicao/agenda/{id}`.
- Histórico: `PATCH /edicao/historico/{id}` · `DELETE /edicao/historico/{id}`.
- Demonstrações: `PATCH /edicao/demonstracoes/{id}` · `DELETE /edicao/demonstracoes/{id}` · `DELETE /edicao/demonstracoes/periodo?cnpj=&data_ref=`.
- Qualitativo: `PATCH /edicao/qualitativo/{id}` · `DELETE /edicao/qualitativo/{id}`.
- Quantitativo: `PATCH /edicao/quantitativo/{id}` · `DELETE /edicao/quantitativo/{id}`.

Erros de banco (ex.: violar `UNIQUE`, FK) → retornar 4xx com mensagem legível para a UI exibir.

## Tarefa C — Frontend (`/gerenciar-dados`)

- **Nav**: incluir "Gerenciar Dados" em `app-nav.tsx` (seguindo a regra de contraste do chrome verde — ver tokens `--chrome-*`).
- **Rota** `app/gerenciar-dados/page.tsx` com as 3 seções (abas internas ou âncoras): Debênture · Emissor · Tabelas mestras. Reusar `entity-selector-combobox` para escolher ticker/emissor.
- **Forms editáveis** (características, emissor): inputs controlados; salvar via PATCH; estados de loading/erro; chaves read-only.
- **Tabelas editáveis** (agenda, histórico, DFs): edição inline por linha (editar/salvar/cancelar), deletar linha, adicionar linha; histórico paginado.
- **Editor de markdown**: `<textarea>` para o conteúdo do compêndio qualitativo + campo de título; botões Salvar/Deletar. (Preview opcional reusando [markdown-viewer.tsx](frontend/components/markdown-viewer.tsx).)
- **Tabelas mestras**: emissores e debêntures com criar/alterar/deletar; deleção mostra o **impacto** (contagens do endpoint `impacto-delecao`) e confirma em **1 clique**.
- **BFF**: route handlers em `app/api/edicao/*` injetando `X-API-Key` (mutações PATCH/POST/DELETE com `cache:"no-store"`). Após mutação, revalidar/refazer fetch da seção afetada.

## Riscos e guard-rails

- **Chaves read-only** (`cnpj`, `ticker_deb`, `id`, `hash_md5`): editá-las quebraria FKs/idempotência. Renomear ticker está **fora de escopo**.
- **Constraints UNIQUE**: editar (ex.) `data_ref`/`data_referencia` para um valor já existente falha — surfacing do erro do DB na UI.
- **Cascata é irreversível** (sem soft delete): por isso o preview de impacto antes do clique.
- **Reprocessamento sobrescreve edições manuais (comportamento ACEITO/intencional)**: o pipeline faz upsert por hash/chave; recadastrar o mesmo ticker/PDF **regrava** características/DFs editadas à mão — e tudo bem, é o esperado. Apenas **documentar na UI** (aviso leve). **Não** construir proteção "sticky" nem bloqueios — fica fora de escopo.
- **Concorrência**: ferramenta mono-operador — ignorar.

## Verificação (end-to-end)

1. **Backend**: subir `uvicorn api.main:app --port 8000`; via `/docs`, exercitar PATCH/DELETE de cada recurso; confirmar erros legíveis em violação de UNIQUE/FK.
2. **Type-check/build do front**: `./node_modules/.bin/tsc --noEmit` e `npm run build` em `frontend/`.
3. **Fluxos manuais** (`npm run dev`):
   - Editar um campo de características → recarregar → persistiu.
   - Deletar um **markdown** subido por engano → some da visão-completa do emissor.
   - Deletar um **período de DF** → some das demonstrações.
   - Deletar uma **debênture** → agenda e histórico somem; emissor permanece.
   - Deletar um **emissor** com filhos → preview mostra contagens; após confirmar, cascata limpa tudo.
   - **Criar** um emissor e uma debênture manualmente → aparecem nas leituras existentes (portfólio/dossiê).
4. **Idempotência de FK**: deletar emissor com debêntures não pode falhar por FK (a ordem da cascata cobre).

## Fora de escopo

- Trilha de auditoria / histórico de alterações; soft delete; multiusuário/permissões.
- Renomear chaves (ticker_deb/cnpj) com propagação.
- Arquivos Office (tratado em outro plano futuro).
- Edição de `pipeline_jobs` e de análises de crédito geradas (além de deletar, se habilitado).
- Proteção "sticky" de edições manuais contra reprocessamento do pipeline.

## Pontos menores assumidos (confirmar se discordar)

1. Nome da aba: **"Gerenciar Dados"**, rota `/gerenciar-dados`.
2. **Create manual** de emissor/debênture cria a linha com os campos mínimos obrigatórios do schema; demais campos ficam nulos até edição/pipeline.
3. Tabelas mestras servem para add/delete rápido + atalho à edição profunda; a edição célula a célula fina mora nas seções por entidade.
4. Análise de crédito: por ora **somente deletar versão** (insert-only mantém o versionamento); sem editor.
