# Plano — Script de comparação de modelos Gemini para extração (2.5 Flash vs 3.1 Flash-Lite)

> O **artefato** é um script descartável em `tmp/comparar_modelos_extracao.py`. Este plano fica versionado para o executor.

## Context

Queremos acelerar a ingestão de PDFs (carga inicial de centenas de emissores) sem perder fidelidade. Análise de custo/qualidade/limites (dados oficiais + benchmarks independentes, jun/2026) apontou o **Gemini 3.1 Flash-Lite** como candidato dominante vs o atual **2.5 Flash**: output ~40% mais barato ($1,50 vs $2,50 / 1M), **RPD 150K vs 10K** (resolve o gargalo da carga fria sem chunks maiores nem Batch API agora), ~45-64% mais rápido, e benchmarks de inteligência/multimodal acima. Ressalvas: é **preview** (estabilidade), benchmark ≠ a tarefa real, e é **modelo de raciocínio** (thinking tokens são cobrados como output).

Decisão do dono: **migrar para 3.1 Flash-Lite, mas validar empiricamente antes** com um script de comparação rodando o mesmo corpus nos dois modelos. Restrição firme do dono: **manter 8 páginas/chunk** (chunk maior já causou truncamento do Gemini no passado). O mecanismo de concorrência (async vs threadpool) fica para **depois** deste teste.

Objetivo: um harness de teste que rode os mesmos PDFs nas duas trilhas (qualitativa = markdown; quantitativa = JSON CVM) com cada modelo e produza um comparativo de **truncamento, fidelidade, latência e custo** para o dono decidir.

## Arquivo a criar

`tmp/comparar_modelos_extracao.py` — script standalone, sequencial, **sem alterar código de produção**. Reaproveita prompts/helpers dos serviços e faz chamadas Gemini **instrumentadas** (os serviços hoje só retornam `.text`; o harness precisa de `finish_reason` e `usage_metadata`, que eles não expõem).

## Design

### Reuso (importar de `scripts_v2/`)
- De `servico_ia_qualitativa.py`: `PROMPT_QUALITATIVO`, `MIN_TEXT_CHARS_PER_PAGE`, `sanitize_extracted_text`, `sanitize_generated_markdown`, `calcular_md5`, `carregar_arquivos_em_memoria`, `CLIENT`. Replicar chunk de **8 páginas** (texto) e a detecção `is_scanned`.
- De `servico_ia_quantitativa.py`: `get_generation_config_quantitativo`, `extract_financial_pages_text_from_bytes`, `is_financial_pdf_name`, `normalizar_resposta_ia`, `merge_periods`, `criar_json_base`.

### Config por modelo (preços oficiais jun/2026, USD / 1M tokens)
- `gemini-2.5-flash`: in $0,30 / out $2,50.
- `gemini-3.1-flash-lite`: in $0,25 / out $1,50.
- **Confirmar o id exato do 3.1** via `client.models.list()`.
- `thinking_budget=0` nos dois (transcrição não precisa de raciocínio; thinking conta como output).

### Wrapper instrumentado
`generate_content` capturando `text`, `finish_reason` (truncado = MAX_TOKENS), `usage_metadata` (prompt/candidates/thoughts tokens), latência e custo. Retry 429/503 (3 tentativas).

### Fluxos
- **Qual** (foco do truncamento): pdfplumber → `is_scanned` → modo texto fatiando 8 págs (mesmo prompt de produção), chamada por chunk, concatena. Modo vision (15 págs) p/ escaneado.
- **Quant**: heurística de nome → `extract_financial_pages_text_from_bytes` → uma chamada JSON (system_instruction + mime json) → `normalizar_resposta_ia`/`merge_periods`.

## Saídas (`tmp/comparacao_modelos/`)
- `por_modelo/<modelo>/<arquivo>.qual.md` e `.quant.json` (revisão humana = juiz final).
- `relatorio.json` e `relatorio.md` lado a lado: latência, tokens, custo USD, nº chunks, **nº chunks truncados**, finish_reasons, chars, períodos/contas.
- Heurística de fidelidade numérica (regex de números; diferença simétrica entre modelos) como sinal, não verdade.

## CLI e guarda de custo
`python tmp/comparar_modelos_extracao.py [pasta] --cnpj --limite N --modo qual|quant|ambos --dry-run`
- Default pasta = `data/01_landing/manual_uploads/02041460000193/Principal`, cnpj `02041460000193`.
- `--limite` default 3 (gasta tokens reais nos 2 modelos). `--dry-run` estima custo sem chamar API.

## Corpus
~3-4 representativos da V.tal: 1 formulário de referência/DFP grande (~80-100 págs) p/ truncamento; 1 escritura/ata (qual longa); 1 release/ITR (quant). Incluir 1 escaneado se houver.

## Verificação
1. `--dry-run` (sem API). 2. `--limite 3 --modo ambos`. 3. Leitura humana das saídas: 3.1 preservou números e **não truncou** os chunks de 8 págs? 4. Custo/latência batem com a tese.

## Follow-up (após decisão)
- Trocar modelo em produção: `MODEL_NAME` (qual) + 2 strings inline (quant, linhas 266/349) → único `GEMINI_MODEL`/env com fallback; `thinking_budget=0`.
- Retomar decisão de **concorrência** (async vs threadpool) + paralelismo de chunks com semáforo global + backoff com jitter.
- Batch API: adiado até o sistema estar pronto/testado.
