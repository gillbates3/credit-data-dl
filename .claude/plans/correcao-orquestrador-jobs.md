# Correção: robustez de jobs no orquestrador V2

> Prompt autocontido para um agente executor (Codex). Alvo: `scripts_v2/orquestrador.py` (e um comentário em `scripts_v2/servico_repositorio.py`). Não alterar nenhum outro arquivo nem mudar a lógica de negócio existente.

## Context

`scripts_v2/orquestrador.py` expõe dois pontos de entrada assíncronos — `ingerir_ticker(...)` e `ingerir_documentos(...)` — que serão chamados pela API (FastAPI `BackgroundTasks`). Cada um atualiza a tabela `pipeline_jobs` conforme progride, para o front fazer polling.

**Problema:** se uma exceção **inesperada** ocorrer, o job fica preso em `status="rodando"` para sempre — nunca grava `"erro"`. Exemplos reais: `repo.salvar_emissor` lança `ValueError` quando `nome_emissor` vem vazio da ANBIMA (chamada **não** protegida em `ingerir_ticker`); ou `repo.buscar_emissor`/`buscar_hashes_*` falham por rede no início de `ingerir_documentos` (trecho **não** protegido). No CLI isso vira só um traceback, mas via API deixa um job-fantasma e o front faz polling indefinidamente.

## Mudança 1 — try/except de borda em `ingerir_ticker`

Envolver **todo o corpo** da função (logo após a criação do dict `progresso`) num `try/except Exception`. Manter os `return` internos existentes (inclusive o caminho de falha de identidade). No `except`, marcar o job como `erro` e relançar (para o log do servidor capturar):

```python
async def ingerir_ticker(ticker, *, deep=False, data_corte_deep=None, job_id=None) -> dict:
    ticker_norm = (ticker or "").strip().upper()
    progresso: dict[str, Any] = { ... }  # inalterado
    try:
        # ... TODO o corpo atual da função, sem mudanças ...
        return { ... }  # retorno de sucesso atual
    except Exception as exc:
        mensagem = f"Falha inesperada em ingerir_ticker({ticker_norm}): {exc}"
        _append_erro(progresso, mensagem)
        await _atualizar_job(job_id, progresso, status="erro", erro=mensagem)
        raise
```

## Mudança 2 — try/except de borda em `ingerir_documentos`

Mesmo padrão: envolver todo o corpo após a criação do `progresso`. Manter o retorno antecipado do "emissor inexistente" e os try/except internos (bloco quantitativo e loop qualitativo) como estão — eles continuam funcionando dentro do try externo.

```python
async def ingerir_documentos(cnpj, arquivos, *, force=False, job_id=None) -> dict:
    cnpj_norm = repo.normaliza_cnpj(cnpj)
    progresso: dict[str, Any] = { ... }  # inalterado
    try:
        # ... TODO o corpo atual ...
        return { ... }  # retorno de sucesso atual
    except Exception as exc:
        mensagem = f"Falha inesperada em ingerir_documentos({cnpj_norm}): {exc}"
        _append_erro(progresso, mensagem)
        await _atualizar_job(job_id, progresso, status="erro", erro=mensagem)
        raise
```

## Mudança 3 — status final `concluido_com_erros`

Quando o pipeline termina mas houve falhas não-fatais acumuladas em `progresso["erros"]`, o status final deve refletir isso em vez de `"concluido"` puro.

Em `ingerir_ticker`, na finalização (hoje `status="concluido"`, etapa `"mercado"`):
```python
status_final = "concluido_com_erros" if progresso["erros"] else "concluido"
await _atualizar_job(job_id, progresso, status=status_final, etapa_atual="mercado")
```
Em `ingerir_documentos`, na finalização (hoje `status="concluido"`, etapa `"finalizado"`):
```python
status_final = "concluido_com_erros" if progresso["erros"] else "concluido"
await _atualizar_job(job_id, progresso, status=status_final, etapa_atual="finalizado")
```

Atualizar também (apenas documentação, não afeta dados) o `COMMENT ON TABLE public.pipeline_jobs` em `scripts_v2/sql/supabase_schema_v2.sql` para listar o novo valor de status: `pendente | rodando | concluido | concluido_com_erros | erro`. Como é só um comentário, não exige re-rodar o schema. A coluna `status` é `text` livre (sem CHECK), então o novo valor já é aceito.

## Mudança 4 — comentário em `montar_demonstracoes_estruturadas`

Em `scripts_v2/servico_repositorio.py`, na reconstrução por `data_ref`, adicionar um comentário curto registrando a premissa (não mudar a lógica):
```python
# Premissa: cada data_ref tem um único tipo_doc (fechamento anual = DFP,
# trimestral = ITR). Se um mesmo data_ref tiver DFP e ITR, o primeiro tipo
# vence e as demonstrações se mesclam — aceitável para o read-model do Passo 6.
```

## Fora de escopo (deixar como está)

- **Não** paralelizar CVM e mercado com `asyncio.gather` agora (otimização; adicionaria risco ao tratamento de erro que estamos endurecendo).
- **Não** alterar assinaturas, contratos de retorno, nem a lógica de deduplicação/persistência.

## Verificação

- `python scripts_v2/orquestrador.py ticker <ticker_invalido>` → o job (se passado `--job-id`) deve terminar como `erro`, não ficar em `rodando`.
- Simular falha de `salvar_emissor` (ex.: emissor sem nome) → job marcado `erro` com mensagem, exceção propagada.
- Fluxo feliz de um ticker com falha não-fatal só em mercado → job `concluido_com_erros`, com a mensagem em `progresso["erros"]`.
- Fluxo feliz completo, sem erros → job `concluido` (comportamento inalterado).
