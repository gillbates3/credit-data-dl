# Plano: implementar `scripts_v2/servico_repositorio.py` (camada de dados V2)

> Este plano é autocontido. O agente executor **não** participou da discussão de arquitetura — todos os contratos necessários estão abaixo. Leia também os arquivos referenciados antes de codar.

## Context

O projeto `credit-data-dl` extrai e consolida dados de debêntures brasileiras. Está sendo refatorado para uma arquitetura V2 ("API-Ready") em `scripts_v2/`, com esta separação de responsabilidades:

- **Serviços de coleta puros** (já prontos): `servico_identidade.py`, `servico_cvm.py`, `servico_mercado.py`, `servico_ia_quantitativa.py`, `servico_ia_qualitativa.py`. Eles recebem input, devolvem `dict`/`str` e **NÃO falam com banco de dados**.
- **Camada de dados** (`servico_repositorio.py` — **este é o objeto deste plano**, ainda não existe): a **única** parte do sistema que conhece o Supabase. Centraliza toda leitura/escrita.
- Acima dela (fases futuras, fora deste plano): `orquestrador.py`, `servico_analise_credito.py`, API FastAPI, front Next.js.

**Princípio de design que justifica este módulo:** só o repositório fala com o banco. Isso o torna a **fronteira de portabilidade** — trocar de banco no futuro deve exigir reescrever apenas este arquivo. Por isso: **geração de ID fica na aplicação** (`uuid.uuid4()`), nunca no banco (`gen_random_uuid()` é proibido), e nenhum SQL cru de regra de negócio vaza para outros módulos.

**Resultado esperado:** um módulo Python **síncrono** que expõe funções atômicas de **leitura** (Peek Before Leap — consultar o que já existe antes de gastar scraping/IA) e **escrita** (adapters que traduzem o formato de cada serviço para colunas + upsert idempotente). O orquestrador (fase futura) o chamará via `await asyncio.to_thread(repo.func, ...)`, então o módulo permanece síncrono e idiomático ao `supabase-py`.

## Pré-requisitos

1. O schema já está definido em [scripts_v2/sql/supabase_schema_v2.sql](../../scripts_v2/sql/supabase_schema_v2.sql). Ele precisa ter sido rodado no SQL Editor do Supabase (DROP+CREATE completo). **Leia esse arquivo** para os nomes/tipos exatos das colunas de cada tabela.
2. Dependências já presentes em [requirements.txt](../../requirements.txt): `supabase`, `python-dotenv`. **Não adicionar dependências novas.**
3. **Variáveis de ambiente:** os serviços V2 carregam de `.env.local` (ver `servico_ia_quantitativa.py:44`), enquanto o script V1 usava `.env`. O repositório precisa de `SUPABASE_URL` e `SUPABASE_KEY` (service_role key, com acesso total de escrita). Carregar com `load_dotenv` tentando **`.env.local` e depois `.env`** como fallback (`load_dotenv` não sobrescreve `os.environ` já populado). Se as variáveis não existirem, levantar `RuntimeError` claro. **Verificar em qual arquivo as chaves Supabase de fato estão antes de assumir.**

## Referência de apoio (padrões a reaproveitar)

O script V1 [scripts/08_upsert_supabase.py](../../scripts/08_upsert_supabase.py) já implementa upserts equivalentes. Reaproveitar dele:
- Init do client: `from supabase import create_client; create_client(url, key)`.
- Helper `batches(lst, n)` com `BATCH_SIZE = 500` (chunking de upserts em lote).
- Helper `normaliza_cnpj(cnpj)` (`re.sub(r"\D", "", cnpj or "")`).
- Padrão de chamada: `client.table("X").upsert(registros, on_conflict="col1,col2").execute()`.

⚠️ **Diferença crítica do V1:** o V2 mudou o UNIQUE de `deb_agenda`. No V1 o `on_conflict` era `"ticker_deb,data_evento,evento"`; no **V2 é `"ticker_deb,data_evento,evento,data_base"`** (o constraint virou `UNIQUE NULLS NOT DISTINCT` com 4 colunas — ver `supabase_schema_v2.sql` seção 6).

## Contratos de entrada (formato exato que cada serviço devolve)

O repositório recebe esses formatos e os traduz para colunas. **Não reprocessar nem reconverter** — os dados já vêm limpos dos serviços.

**`servico_identidade.buscar_identidade_emissor(ticker)`** →
```python
{"ticker": str, "nome_emissor": str|None, "cnpj_emissor": str|None,  # já normalizado (só dígitos)
 "cod_cvm": str|None, "categoria_cvm": str|None,
 "tipo_capital": "Aberto"|"Fechado", "status": "SUCESSO"|"ERRO"|...}
```
Mapeia para tabela `emissores`: `cnpj_emissor`→`cnpj`, `nome_emissor`→`nome`, mais `cod_cvm`, `categoria_cvm`, `tipo_capital`. (As colunas `ticker_acao`, `grupo_economico`, `setor`, `observacao` NÃO vêm da identidade — são manuais; não tocar.)

**`servico_cvm.buscar_dados_cvm(cnpj, cod_cvm)`** e **`servico_ia_quantitativa.extrair_dados_quantitativos(...)`** devolvem o **MESMO** formato de `periodos`:
```python
{"cnpj": str, "cod_cvm": str,              # cvm tem cod_cvm; quant NÃO tem
 "periodos": {
   "YYYY-MM-DD": {
     "tipo": "DFP"|"ITR",
     "demonstracoes": {
       "BPA": {"1": {"cd_conta": "1", "ds_conta": "Ativo Total", "valor": 123.45}, ...},
       "BPP": {...}, "DRE": {...}, "DFC": {...}, "DVA": {...}}}},
 "processed_files": [{"nome_arquivo": str, "hash_md5": str}]}  # SÓ no quantitativo
```
**Implicação:** um único adapter `periodos_para_linhas(cnpj, resultado)` serve às DUAS fontes (achata `resultado["periodos"]`). O quantitativo tem adicionalmente `processed_files` (usado para o manifesto).

**`servico_mercado.buscar_dados_mercado(ticker)`** →
```python
{"ticker_deb": str,
 "caracteristicas": {...},          # dict sem cnpj e sem ticker_deb dentro — INJETAR ambos
 "agenda": [{data_evento, data_base, data_liquidacao, evento, evento_arc,
             taxa, valor, status, grupo_status}, ...],   # itens sem cnpj/ticker_deb — INJETAR
 "historico_diario": [{data_referencia, pu_par, vna, ...todas as colunas...}, ...]}  # injetar ticker_deb
```
As chaves de `caracteristicas` e de cada item de `historico_diario` já batem 1:1 com as colunas das tabelas `deb_caracteristicas` / `deb_historico_diario` (ver `servico_mercado.py` linhas 355–402 e o schema).

**`servico_ia_qualitativa.extrair_dados_qualitativos(cnpj, [(nome,bytes)], incluir_frontmatter=False)`** → devolve uma **string markdown** (corpo de um arquivo). O **chamador (orquestrador)** computa o MD5 dos bytes do PDF e chama `salvar_compendio_qualitativo(cnpj, nome_arquivo, hash_md5, markdown)`. **O repositório NÃO computa hash** — recebe pronto.

## Estrutura do módulo a implementar

**Conexão e helpers:**
- `_get_client() -> Client`: singleton lazy (variável de módulo). Faz `load_dotenv(.env.local)` + `load_dotenv(.env)`, lê `SUPABASE_URL`/`SUPABASE_KEY`, `create_client`, cacheia. `RuntimeError` se faltar env.
- `BATCH_SIZE = 500`; `_batches(lst, n)`; `normaliza_cnpj(cnpj)`.

**Leitura — Peek Before Leap** (todas usam `client.table(...).select(...).eq("cnpj"/"ticker_deb", ...).execute().data`):

| Função | Tabela/View | Retorno | Notas |
|---|---|---|---|
| `buscar_emissor(cnpj)` | emissores | `dict \| None` | primeiro registro ou None |
| `buscar_hashes_qualitativo(cnpj)` | emissor_compendio_qualitativo | `set[str]` | select `hash_md5` → set |
| `buscar_hashes_quantitativo(cnpj)` | emissor_compendio_quantitativo | `set[str]` | select `hash_md5` → set |
| `buscar_periodos_demonstracoes(cnpj)` | demonstracoes_financeiras | `set[str]` | select `data_ref`, dedupe em Python (datas vêm como "YYYY-MM-DD") |
| `buscar_datas_historico(ticker_deb)` | deb_historico_diario | `set[str]` | select `data_referencia`, dedupe |
| `buscar_ultima_analise(cnpj)` | v_ultima_analise_credito | `dict \| None` | para o delta do Passo 6 |
| `montar_demonstracoes_estruturadas(cnpj)` | demonstracoes_financeiras | `dict` | lê todas as linhas e **remonta** o `periodos` aninhado (inverso de `periodos_para_linhas`), para alimentar o LLM. Em memória, não persiste. |

**Escrita — adapters + upsert:**

| Função | Tabela | `on_conflict` / modo |
|---|---|---|
| `salvar_emissor(identidade)` | emissores | upsert `on_conflict="cnpj"` (adapter de chaves descrito acima) |
| `salvar_caracteristicas(cnpj, ticker_deb, caracteristicas)` | deb_caracteristicas | injeta `cnpj`+`ticker_deb` no dict; upsert `on_conflict="ticker_deb"` |
| `salvar_agenda(cnpj, ticker_deb, agenda)` | deb_agenda | injeta `cnpj`+`ticker_deb` por item; **bulk** upsert `on_conflict="ticker_deb,data_evento,evento,data_base"` → retorna `int` |
| `salvar_historico(ticker_deb, historico)` | deb_historico_diario | injeta `ticker_deb` por item; **bulk** upsert `on_conflict="ticker_deb,data_referencia"` → `int` |
| `periodos_para_linhas(cnpj, resultado)` | — | **adapter** (helper): achata `resultado["periodos"]` em `list[dict]` no formato canônico `{cnpj, data_ref, tipo_doc, demonstracao, cd_conta, ds_conta, valor}`. Note: `tipo`→`tipo_doc`, chave do período→`data_ref`, chave da demonstração (BPA/...)→`demonstracao` |
| `salvar_demonstracoes(linhas)` | demonstracoes_financeiras | **bulk** upsert `on_conflict="cnpj,data_ref,tipo_doc,demonstracao,cd_conta"` → `int` |
| `salvar_compendio_qualitativo(cnpj, nome_arquivo, hash_md5, markdown, force=False)` | emissor_compendio_qualitativo | upsert `on_conflict="cnpj,hash_md5"`; `ignore_duplicates=True` (DO NOTHING) quando `force=False`, `False` (DO UPDATE) quando `force=True` |
| `salvar_compendio_quantitativo(cnpj, nome_arquivo, hash_md5, force=False)` | emissor_compendio_quantitativo | idem (só manifesto, sem markdown) |
| `salvar_analise_credito(cnpj, analise_markdown, delta_markdown, metadados)` | emissor_analise_credito | **insert puro** (`.insert(...)`, sem on_conflict — tabela é insert-only/versionada) |

**Jobs (CRUD da tabela `pipeline_jobs`, para o front fazer polling):**
- `criar_job(tipo, alvo) -> str`: gera `job_id = str(uuid.uuid4())`, insere `{id, tipo, alvo, status:"pendente"}`, devolve `job_id`. (`tipo` ∈ `"ingestao"|"analise"`; `alvo` = ticker ou cnpj.)
- `atualizar_job(job_id, *, status=None, etapa_atual=None, progresso=None, erro=None)`: monta dict só com os campos não-None e faz `.update(d).eq("id", job_id).execute()`.
- `buscar_job(job_id) -> dict | None`.

## Decisões de implementação (seguir à risca)

- **Síncrono, funções de módulo** (não classe), por consistência com os demais `servico_*.py`. A portabilidade vem de todo acesso a banco estar neste único arquivo.
- **Atomicidade hash+números sem lock-in:** no fluxo quantitativo (responsabilidade do orquestrador na fase futura, mas o repositório deve suportar a ordem), as escritas devem ocorrer **`salvar_demonstracoes` ANTES, `salvar_compendio_quantitativo` (manifesto) DEPOIS**. Se houver crash no meio, o manifesto fica ausente → próxima execução reprocessa o PDF → `salvar_demonstracoes` faz upsert idempotente (não duplica) → manifesto é gravado. Isso garante consistência **sem** transação multi-tabela nem função no banco (preserva portabilidade). Documentar isso num comentário nas funções de compêndio.
- **DO NOTHING:** usar o parâmetro `ignore_duplicates=True` do `.upsert()` do supabase-py para o caso `force=False` dos compêndios.
- **IDs:** `pipeline_jobs.id` é `str(uuid.uuid4())` gerado aqui. Nunca usar default do banco.
- **Bulk real:** `salvar_demonstracoes`, `salvar_historico` e `salvar_agenda` recebem listas e fazem upsert em lotes de `BATCH_SIZE`, nunca linha-a-linha.

## Arquivos

- **Criar:** `scripts_v2/servico_repositorio.py`.
- **Não alterar** nenhum outro arquivo (as assinaturas V2 dos serviços já estão prontas).

## Verificação

1. Garantir que [scripts_v2/sql/supabase_schema_v2.sql](../../scripts_v2/sql/supabase_schema_v2.sql) foi rodado no Supabase.
2. Adicionar um bloco `if __name__ == "__main__":` de smoke test (espelhando o padrão dos outros `servico_*.py`) que, contra o Supabase real:
   - `_get_client()` conecta sem erro;
   - `criar_job("ingestao", "TESTE11")` → devolve job_id; `atualizar_job(job_id, status="rodando", etapa_atual="identidade")`; `buscar_job(job_id)` reflete a mudança;
   - `salvar_emissor({...CNPJ fictício...})` e `buscar_emissor(cnpj)` recupera o registro;
   - `buscar_hashes_qualitativo(cnpj)` retorna `set()` vazio para CNPJ novo;
   - `periodos_para_linhas` + `salvar_demonstracoes` com um período de exemplo; rodar **duas vezes** e confirmar (via `buscar_periodos_demonstracoes` e contagem) que **não duplica** (idempotência).
3. Limpar os registros de teste ao final (ou usar um CNPJ claramente fictício como `99999999999999`).

## Roadmap (fora do escopo deste plano)

Após o repositório: `orquestrador.py` (costura serviços + repo, aplica Peek Before Leap, atualiza `pipeline_jobs`) → `servico_analise_credito.py` (Passo 6, delta via LLM) → API FastAPI (BackgroundTasks + `pipeline_jobs`) → front Next.js (views + polling de `v_jobs_recentes`).
