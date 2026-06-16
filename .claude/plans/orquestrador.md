# Plano: implementar `scripts_v2/orquestrador.py` (maestro do pipeline V2)

> Plano autocontido para delegar a um agente executor (Codex) que **não** participou da discussão. Todos os contratos estão abaixo. Leia os arquivos referenciados antes de codar.

## Context

`credit-data-dl` (extração de dados de debêntures brasileiras) está em refactoring V2 em `scripts_v2/`. A arquitetura tem três camadas: **serviços de coleta puros** (não falam com banco), **camada de dados** (`servico_repositorio.py` — única que fala com Supabase) e o **orquestrador** (este plano), que sequencia os serviços, aplica deduplicação ("Peek Before Leap") e persiste via repositório.

**Dependência:** este plano assume que `scripts_v2/servico_repositorio.py` já existe com a interface descrita no plano [servico_repositorio.md](servico_repositorio.md) (está sendo implementado em paralelo). Os nomes/assinaturas das funções do repositório usadas aqui vêm desse plano.

**Roadmap (ordem acordada):** repositório → **orquestrador (este)** → API FastAPI → front Next.js → `servico_analise_credito.py` (Passo 6) por último. **Portanto este plano cobre só a INGESTÃO (P1–P4). Não inclui análise de crédito (P6).**

**Resultado esperado:** módulo Python **assíncrono** (`orquestrador.py`) com **dois pontos de entrada** (decisão do dono): `ingerir_ticker(...)` (dados automáticos ANBIMA+CVM) e `ingerir_documentos(...)` (PDFs de upload). Ele será chamado pela API via FastAPI `BackgroundTasks`, atualizando a tabela `pipeline_jobs` para o front fazer polling.

## Contratos dos serviços que o orquestrador chama

**Assíncronos (usar `await`):**
- `servico_identidade.buscar_identidade_emissor(ticker: str)` → `{"ticker", "nome_emissor", "cnpj_emissor" (só dígitos), "cod_cvm"|None, "categoria_cvm"|None, "tipo_capital": "Aberto"|"Fechado", "status": "SUCESSO"|"ERRO"|...}`
- `servico_cvm.buscar_dados_cvm(cnpj: str, codigo_cvm: str, anos_retroativos=2)` → `{"cnpj","cod_cvm","periodos": {...}}` (formato `periodos` idêntico ao do quantitativo)
- `servico_mercado.buscar_dados_mercado(ticker: str, deep=False, data_corte_deep=None, datas_desconhecidas=None)` → `{"ticker_deb","caracteristicas": {...sem cnpj/ticker...}, "agenda": [...], "historico_diario": [...]}`

**Síncronos (envolver em `await asyncio.to_thread(...)` — bloqueiam no Gemini):**
- `servico_ia_quantitativa.extrair_dados_quantitativos(cnpj, arquivos_em_memoria, periodos_existentes_db=None)` → `{"cnpj","periodos": {...}, "processed_files": [{"nome_arquivo","hash_md5"}]}`. **Auto-filtra** PDFs não-financeiros (`is_financial_pdf_name`); só os financeiros entram em `processed_files`.
- `servico_ia_qualitativa.extrair_dados_qualitativos(cnpj, arquivos_em_memoria, markdown_existente="", incluir_frontmatter=True)` → **string markdown**. **NÃO filtra** por nome — transcreve qualquer PDF. Quando `incluir_frontmatter=False` e a lista tem **um** arquivo, retorna só o corpo markdown daquele arquivo.

`arquivos_em_memoria` é sempre `list[tuple[str, bytes]]` = `(nome_arquivo, conteudo_pdf)`.

## Contratos do repositório usados (de `servico_repositorio.md`)

Todos **síncronos** → chamar via `await asyncio.to_thread(repo.func, ...)`.
- Leitura: `buscar_emissor(cnpj)`, `buscar_hashes_quantitativo(cnpj)→set`, `buscar_hashes_qualitativo(cnpj)→set`, `buscar_periodos_demonstracoes(cnpj)→set`, `buscar_datas_historico(ticker)→set`.
- Escrita: `salvar_emissor(identidade)`, `salvar_caracteristicas(cnpj, ticker, caracteristicas)`, `salvar_agenda(cnpj, ticker, agenda)`, `salvar_historico(ticker, historico)`, `periodos_para_linhas(cnpj, resultado)→list`, `salvar_demonstracoes(linhas)`, `salvar_compendio_quantitativo(cnpj, nome, hash_md5, force=False)`, `salvar_compendio_qualitativo(cnpj, nome, hash_md5, markdown, force=False)`.
- Jobs: `criar_job(tipo, alvo)→job_id`, `atualizar_job(job_id, *, status=, etapa_atual=, progresso=, erro=)`, `buscar_job(job_id)`.

## Regra de roteamento de PDFs (importante)

O orquestrador passa a **mesma lista de PDFs** para os dois serviços de IA; cada um se auto-seleciona:
- O **quantitativo** auto-descarta não-financeiros (escrituras, ratings) e extrai números dos financeiros.
- O **qualitativo** transcreve **todos** para markdown.
- Um DFP entra nos dois (números + narrativa). Uma escritura só no qualitativo. **Não há classificação manual.**
- Deduplicação é **independente** por serviço (cada tabela de compêndio tem seu próprio conjunto de hashes). O mesmo md5 pode existir nas duas tabelas.

## Ponto de entrada 1 — `ingerir_ticker`

```python
async def ingerir_ticker(ticker: str, *, deep: bool = False,
                         data_corte_deep: str | None = None,
                         job_id: str | None = None) -> dict
```
Cobre **P1 Identidade → P2 CVM → P3 Mercado**. Passos (atualizar `etapa_atual` do job a cada um, se `job_id`):

1. **(`etapa="identidade"`)** `identidade = await buscar_identidade_emissor(ticker)`. Se `identidade["status"] != "SUCESSO"` → `atualizar_job(job_id, status="erro", erro=...)` e retornar. Extrair `cnpj = identidade["cnpj_emissor"]`, `cod_cvm`, `tipo_capital`.
2. **Persistir emissor:** `await asyncio.to_thread(repo.salvar_emissor, identidade)`.
3. **(`etapa="cvm"`)** Só se `cod_cvm` presente (empresa **Aberta**). `resultado_cvm = await buscar_dados_cvm(cnpj, cod_cvm)`; `linhas = await to_thread(repo.periodos_para_linhas, cnpj, resultado_cvm)`; `await to_thread(repo.salvar_demonstracoes, linhas)`. Se **Fechada / sem cod_cvm** → pular CVM (registrar em `progresso`; financeiro virá só de PDFs). Envolver em try/except: falha de CVM é **não-fatal** (registrar em `progresso["erros"]`, seguir).
4. **(`etapa="mercado"`)** `resultado_mkt = await buscar_dados_mercado(ticker, deep=deep, data_corte_deep=data_corte_deep, datas_desconhecidas=None)`. Persistir, nesta ordem:
   - `await to_thread(repo.salvar_caracteristicas, cnpj, ticker, resultado_mkt["caracteristicas"])`
   - `await to_thread(repo.salvar_agenda, cnpj, ticker, resultado_mkt["agenda"])`
   - `await to_thread(repo.salvar_historico, ticker, resultado_mkt["historico_diario"])`
   Try/except: falha de mercado é **não-fatal**.
5. **Finalizar:** `atualizar_job(job_id, status="concluido", progresso={...})`. Retornar resumo `{ticker, cnpj, tipo_capital, periodos_cvm, eventos_agenda, dias_historico, erros}`.

**Sobre `deep` (decisão: desligado por padrão):** expor `deep` e `data_corte_deep` como parâmetros (a API os repassa do front). Com `deep=False` (default), o mercado roda só a camada light (rápida) — não usa a calculadora. Com `deep=True`, passar `datas_desconhecidas=None` por ora (preenche todas as taxas faltantes; o upsert de histórico é idempotente). **TODO documentado no código:** um filtro mais fino exigiria o serviço de mercado expor a lista de datas candidatas; a semântica atual de `datas_desconhecidas` é whitelist, então use `data_corte_deep` para limitar o período.

## Ponto de entrada 2 — `ingerir_documentos`

```python
async def ingerir_documentos(cnpj: str, arquivos: list[tuple[str, bytes]], *,
                            force: bool = False, job_id: str | None = None) -> dict
```
Cobre **P4a Quantitativo + P4b Qualitativo** sobre PDFs de upload. Pré-condição: o emissor já deve existir (o usuário roda `ingerir_ticker` antes).

1. **Validar emissor:** `if await to_thread(repo.buscar_emissor, cnpj) is None:` → `atualizar_job(status="erro", erro="emissor inexistente; rode ingerir_ticker primeiro")` e retornar. (Evita violar a FK dos compêndios.)
2. **Peek de hashes:** `hashes_quant = await to_thread(repo.buscar_hashes_quantitativo, cnpj)`; `hashes_qual = await to_thread(repo.buscar_hashes_qualitativo, cnpj)`.
3. **Pré-filtrar por md5** (o orquestrador computa `hashlib.md5(bytes).hexdigest()`):
   - `novos_quant = [(n,b) for (n,b) in arquivos if force or _md5(b) not in hashes_quant]`
   - `novos_qual  = [(n,b) for (n,b) in arquivos if force or _md5(b) not in hashes_qual]`
   (Subconjuntos **independentes** — um arquivo pode ser novo só para um dos serviços.)
4. **(`etapa="ia_quant"`)** Se `novos_quant`:
   - `periodos_db = list(await to_thread(repo.buscar_periodos_demonstracoes, cnpj))`
   - `resultado_q = await to_thread(extrair_dados_quantitativos, cnpj, novos_quant, periodos_db)`
   - **Ordem de escrita (atomicidade por ordenação — ver repo plan):** primeiro demonstrações, depois manifesto.
     - `linhas = await to_thread(repo.periodos_para_linhas, cnpj, resultado_q)`; `await to_thread(repo.salvar_demonstracoes, linhas)`
     - Para cada `pf` em `resultado_q["processed_files"]`: `await to_thread(repo.salvar_compendio_quantitativo, cnpj, pf["nome_arquivo"], pf["hash_md5"], force)`
   - (O manifesto recebe só os arquivos que o serviço realmente processou — financeiros.)
5. **(`etapa="ia_qual"`)** Se `novos_qual`: processar **um arquivo por vez** (1 linha por PDF no banco):
   - Para cada `(nome, bytes)` em `novos_qual`:
     - `md5 = _md5(bytes)`
     - `markdown = await to_thread(extrair_dados_qualitativos, cnpj, [(nome, bytes)], "", False)`  *(markdown_existente="", incluir_frontmatter=False)*
     - `if markdown.strip(): await to_thread(repo.salvar_compendio_qualitativo, cnpj, nome, md5, markdown, force)` (markdown vazio → pular, registrar).
6. **Finalizar:** `atualizar_job(status="concluido", progresso={...})`. Retornar `{cnpj, quant_processados, qual_processados, pulados_quant, pulados_qual, erros}`.

## Regras transversais

- **Ponte async/sync:** `await` direto nos serviços assíncronos (identidade, cvm, mercado); `await asyncio.to_thread(...)` para os síncronos (ia_quant, ia_qual, **todas** as chamadas ao repositório).
- **Helper de md5:** definir local `def _md5(b: bytes) -> str: return hashlib.md5(b).hexdigest()` (mesmo algoritmo que os serviços de IA usam, garantindo hashes consistentes).
- **Job opcional:** todo `atualizar_job` deve ser guardado por `if job_id:`. Com `job_id=None` (teste via CLI) o pipeline roda sem rastreio.
- **Quem cria o job:** o orquestrador **não cria** jobs — ele só atualiza. A API (fase futura) chama `repo.criar_job("ingestao", ticker)` (ou `"analise"`), retorna o `job_id` ao front na hora, e dispara `BackgroundTasks` → `ingerir_ticker(..., job_id=job_id)`. Documentar esse contrato num comentário no topo do módulo.
- **`progresso` (jsonb):** dict acumulado, ex.: ticker → `{"passos_concluidos": [...], "periodos_cvm": N, "eventos_agenda": N, "dias_historico": N, "erros": [...]}`; documentos → `{"quant_processados": N, "qual_processados": N, "pulados_quant": N, "pulados_qual": N, "erros": [...]}`.
- **Tratamento de erro:** em `ingerir_ticker`, falha de **identidade é fatal**; falhas de **CVM e mercado são não-fatais** (try/except por passo, acumular em `progresso["erros"]`, job termina `"concluido"` mesmo com avisos, ou `"erro"` só se nada foi persistido). Em `ingerir_documentos`, isolar cada arquivo do qualitativo em try/except (o serviço já faz por dentro, mas o save é externo).

## Arquivos

- **Criar:** `scripts_v2/orquestrador.py`.
- **Não alterar** os serviços nem o repositório.

## Verificação

Bloco `if __name__ == "__main__":` com CLI (espelhando o padrão dos outros `servico_*.py`), usando `asyncio.run`:
- `python scripts_v2/orquestrador.py ticker PETR26` → roda `ingerir_ticker("PETR26")`, imprime o resumo; conferir no Supabase que `emissores`, `demonstracoes_financeiras`, `deb_caracteristicas`, `deb_agenda`, `deb_historico_diario` foram populados.
- `python scripts_v2/orquestrador.py docs <CNPJ> <pasta_pdfs>` → carrega PDFs com `servico_ia_quantitativa.carregar_arquivos_em_memoria(Path(...))` (ou função equivalente), roda `ingerir_documentos(cnpj, arquivos)`, imprime resumo; conferir `demonstracoes_financeiras`, `emissor_compendio_quantitativo` e `emissor_compendio_qualitativo`.
- **Idempotência:** rodar cada comando **duas vezes** e confirmar que a segunda execução pula tudo por hash/upsert (nada duplica; contagens estáveis).
- Testar empresa **Fechada** (sem cod_cvm) para confirmar que CVM é pulado sem quebrar o fluxo.

## Roadmap (fora do escopo)

Depois: API FastAPI (cria job, dispara `ingerir_ticker`/`ingerir_documentos` em `BackgroundTasks`, expõe `GET` das views e `v_jobs_recentes`) → front Next.js (botões 'Adicionar ticker' e 'Enviar documentos' + polling de status) → `servico_analise_credito.py` (Passo 6).
