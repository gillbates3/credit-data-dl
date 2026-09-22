# Plano: escala de moeda híbrida em `demonstracoes_financeiras` (valor canônico em reais + metadados de origem)

> **Entrega:** spec autocontido para um agente executor (Codex) que **não** tem o histórico desta conversa. Idioma do projeto: **pt-BR**. Plataforma: **Windows** (PowerShell + Bash). Leia os arquivos citados antes de codar. Ao terminar, rode os testes da seção 12 e atualize o HANDOVER (§ correspondente).

> **Contexto/canônico:** arquitetura V2 em `.claude/plans/HANDOVER.md`. Este plano toca as **duas trilhas de dados quantitativos** (CVM e documento via LLM), o **repositório**, o **schema Supabase**, a **API** e o **front**.

---

## 1. Motivação (bug descoberto) e decisão

### 1.1 Bug encontrado (comprovado com dados reais da CVM)
`servico_cvm.parse_valor` assume formato **BR** e remove todo `.`:
```python
# ATUAL (ERRADO)
v = str(valor_str).strip().replace(".", "").replace(",", ".")
return float(v)
```
Mas o CSV de dados abertos da CVM traz `VL_CONTA` em **formato US (ponto = decimal)**, ex.: `'2326714.0000000000'`. O parser vira isso em `"23267140000000000"` → `2.326714e16`. Além disso, a coluna **`ESCALA_MOEDA`** (ex.: `MIL`) é **ignorada** — os valores estão em **milhares de reais**.

Resultado real observado (Alares, cod_cvm 25194, Ativo Total 2026-06-30):
- `VL_CONTA` cru = `2326714.0000000000`, `ESCALA_MOEDA=MIL`
- Gravado hoje: `23.267.140.000.000.000` ❌
- Correto (reais cheios): `2.326.714 × 1000 = 2.326.714.000` (≈ R$ 2,33 bi) ✅

### 1.2 Decisão do dono (travada)
Adotar modelo **híbrido**: manter o `valor` **canônico em REAIS CHEIOS (unidade)** — que é o que todos os consumidores usam — **e** guardar **duas colunas novas** com a origem, para auditoria e correção reversível:
- `valor_origem` — o número exatamente como reportado na fonte (ex.: `2326714`).
- `escala_origem` — a escala da fonte (`unidade` | `mil` | `milhao`).

Relação invariante: **`valor = valor_origem × fator(escala_origem)`**.

Justificativas do dono:
- Consumo direto sempre em reais cheios (não se soma reais de empresas diferentes; comparações são **intra-empresa**, onde a escala costuma ser consistente entre períodos).
- Guardar `escala_origem`/`valor_origem` dá auditabilidade e permite corrigir uma escala mal-lida (principalmente vinda de PDF por LLM) **sem re-ingestão**.
- **A mesma normalização vale nas DUAS trilhas** (CVM e documento/LLM), senão CVM e documento ficam em unidades diferentes.
- **Qualquer validação de dados deve considerar a escala** — na prática, validar sempre sobre o `valor` canônico (reais cheios).

---

## 2. Modelo de dados alvo (`demonstracoes_financeiras`)

Colunas atuais (ver `scripts_v2/sql/supabase_schema_v2.sql`): `id, cnpj, data_ref, tipo_doc, demonstracao, cd_conta, ds_conta, valor numeric, criado_em`. UNIQUE `(cnpj, data_ref, tipo_doc, demonstracao, cd_conta)`.

**Adicionar exatamente 2 colunas:**

| coluna | tipo | semântica |
|---|---|---|
| `valor` (existente) | `numeric` | **CANÔNICO — reais cheios (unidade).** É o que API/front/SQL/LLM consomem. |
| `valor_origem` (nova) | `numeric` | valor como reportado na fonte (sem aplicar escala). |
| `escala_origem` (nova) | `text` | `unidade` \| `mil` \| `milhao` (minúsculo, normalizado). |

Regras:
- `valor` **nunca** é nulo quando há dado; `valor = valor_origem × fator(escala_origem)`.
- `escala_origem` default `'unidade'` (compatível com legado onde não havia escala).
- Não trocar a UNIQUE nem o tipo de `valor` (já é `numeric`).

> Decisão de escopo: **NÃO** adicionar coluna `moeda` agora (assume-se BRL). Deixar como extensão futura documentada (seção 13).

---

## 3. Novo módulo utilitário compartilhado: `scripts_v2/escala_moeda.py`

Fonte única da normalização, importada pelas duas trilhas. Sem dependências pesadas.

```python
"""Normalização de escala de moeda para reais cheios (unidade).

Fonte única usada pelas trilhas CVM e quantitativa. Convenção canônica do banco:
`demonstracoes_financeiras.valor` está SEMPRE em reais cheios (unidade).
"""
from __future__ import annotations

# escala canônica -> fator multiplicador para chegar a reais cheios
_FATORES = {"unidade": 1, "mil": 1_000, "milhao": 1_000_000}

def normalizar_escala(bruto: str | None) -> str:
    """Mapeia rótulos de fonte (CVM 'MIL'/'UNIDADE', headers de PDF, etc.) para
    a escala canônica {'unidade','mil','milhao'}. Default: 'unidade'."""
    if not bruto:
        return "unidade"
    t = str(bruto).strip().lower()
    # remove acentos comuns
    t = (t.replace("ã", "a").replace("á", "a").replace("â", "a")
           .replace("õ", "o").replace("ó", "o").replace("ô", "o"))
    if t in ("mil", "milhar", "milhares"):
        return "mil"
    if t in ("milhao", "milhoes", "milhao de reais", "milhoes de reais"):
        return "milhao"
    if t in ("unidade", "unidades", "real", "reais", "1"):
        return "unidade"
    # heurística: contém 'milho' -> milhao; contém 'mil' -> mil
    if "milho" in t:
        return "milhao"
    if "mil" in t:
        return "mil"
    return "unidade"

def fator_escala(escala: str | None) -> int:
    return _FATORES.get(normalizar_escala(escala), 1)

def para_reais(valor_origem, escala: str | None):
    """Converte (valor_origem, escala) -> reais cheios. Retorna None se valor_origem None."""
    if valor_origem is None:
        return None
    return valor_origem * fator_escala(escala)
```

> Nota: `float × int` pode gerar imprecisão; ver seção 11 (usar o valor já como número; o Postgres armazena em `numeric`). Se preferir robustez total, aceitar `valor_origem` como `Decimal` — opcional; o schema `numeric` absorve.

---

## 4. Schema Supabase — DDL

### 4.1 Migração (banco existente) — rodar no SQL Editor
```sql
ALTER TABLE public.demonstracoes_financeiras
    ADD COLUMN IF NOT EXISTS valor_origem  numeric,
    ADD COLUMN IF NOT EXISTS escala_origem text;

-- Backfill conservador do legado (ver seção 10 sobre re-ingestão):
UPDATE public.demonstracoes_financeiras
   SET escala_origem = COALESCE(escala_origem, 'unidade')
 WHERE escala_origem IS NULL;

ALTER TABLE public.demonstracoes_financeiras
    ADD CONSTRAINT chk_escala_origem
    CHECK (escala_origem IN ('unidade','mil','milhao'));
```

### 4.2 Atualizar o script canônico `scripts_v2/sql/supabase_schema_v2.sql`
No `CREATE TABLE public.demonstracoes_financeiras`, adicionar as colunas e o CHECK:
```sql
    valor         numeric,        -- CANÔNICO: reais cheios (unidade)
    valor_origem  numeric,        -- valor como reportado na fonte
    escala_origem text DEFAULT 'unidade'
                  CHECK (escala_origem IN ('unidade','mil','milhao')),
```
Atualizar o `COMMENT ON TABLE` explicando que `valor` é sempre reais cheios e `valor_origem`/`escala_origem` preservam a origem.

> ⚠️ O `supabase_schema_v2.sql` é **DROP+CREATE** (apaga dados) — serve para banco novo. Para o banco atual use a migração 4.1.

---

## 5. Trilha CVM — `scripts_v2/servico_cvm.py`

### 5.1 Corrigir `parse_valor` (bug do separador)
```python
def parse_valor(valor_str: str) -> float | None:
    """CVM usa PONTO como separador decimal e NÃO usa separador de milhar."""
    if valor_str is None:
        return None
    v = str(valor_str).strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None
```
Remover o `.replace(".", "").replace(",", ".")`. (Se quiser robustez a um eventual formato BR, tratar só o caso com `,`: se houver `,` e `.`, é BR; senão, ponto-decimal. Mas os dados abertos da CVM são ponto-decimal — manter simples.)

### 5.2 Ler `ESCALA_MOEDA` e produzir valor canônico + origem
Em `processar_linhas`, para cada linha:
```python
import escala_moeda  # ou: from scripts_v2 import escala_moeda (com try/except como nos outros módulos)

escala = escala_moeda.normalizar_escala(linha.get("ESCALA_MOEDA"))
valor_origem = parse_valor(vl_conta_str)
if valor_origem is None:
    continue
valor = escala_moeda.para_reais(valor_origem, escala)

por_periodo[dt_refer][cd_conta] = {
    "cd_conta": cd_conta,
    "ds_conta": ds_conta,
    "valor": valor,               # reais cheios
    "valor_origem": valor_origem, # como veio no CSV
    "escala_origem": escala,      # 'unidade'|'mil'|'milhao'
}
```
Manter a lógica de `nivel_conta`/`NIVEL_MAX` e o skip de `ORDEM_EXERC` penúltimo.

> Observação: a `MOEDA` da CVM é `REAL`; assumir BRL. Não há linhas de índice/percentual nessas tabelas (BPA/BPP/DRE/DFC/DVA são monetárias), então aplicar escala uniformemente é correto.

---

## 6. Trilha quantitativa (documento/LLM) — `scripts_v2/servico_ia_quantitativa.py`

Hoje a quant estrutura o Markdown via Gemini em JSON `{"periodos": {data: {tipo, demonstracoes: {DEM: {cd_conta: {cd_conta, ds_conta, valor}}}}}}` (ver `system_instruction_quantitativa` / `extrair_quant_de_markdown`). **Problema:** o LLM às vezes já expande a escala (ex.: "R$252M" → 252000000) e às vezes não — comportamento não-determinístico.

### 6.1 Tornar a escala explícita e determinística
Alterar o **prompt** (`system_instruction_quantitativa`) para:
- Instruir: **"Não aplique escala. Transcreva o número EXATAMENTE como aparece na tabela (isso é `valor_origem`). Informe a escala do quadro no campo `escala` de cada período: `unidade`, `mil` ou `milhao`, lendo cabeçalhos como 'em milhares de reais' / 'R$ mil' / 'em milhões' / 'R$'."**
- Adicionar `escala` ao formato de saída, **por período**:
```json
{ "periodos": { "YYYY-MM-DD": {
    "tipo": "DFP",
    "escala": "mil",
    "demonstracoes": { "BPA": { "1": {"cd_conta":"1","ds_conta":"Ativo Total","valor": 2326714} } }
} } }
```
(escala por período cobre o caso usual de 1 escala por documento/quadro; se o doc misturar escalas por demonstração, aceitar `escala` também dentro de cada demonstração como override — opcional; ver seção 13.)

### 6.2 Normalizar ao montar as contas
Em `extrair_quant_de_markdown` (ou logo após `normalizar_resposta_ia`), para cada conta, transformar em `{cd_conta, ds_conta, valor, valor_origem, escala_origem}`:
```python
import escala_moeda
...
for data_ref, per in (resultado.get("periodos") or {}).items():
    escala_periodo = escala_moeda.normalizar_escala(per.get("escala"))
    for dem, contas in (per.get("demonstracoes") or {}).items():
        for cd, c in (contas or {}).items():
            vo = c.get("valor")               # o LLM devolve o número como impresso
            c["valor_origem"] = vo
            c["escala_origem"] = escala_periodo
            c["valor"] = escala_moeda.para_reais(vo, escala_periodo)
```
Garantir que `normalizar_resposta_ia` **não** descarte o novo campo `escala`.

> Compatibilidade: se o LLM não devolver `escala`, cair em `'unidade'` (o `para_reais` já faz isso). Isso mantém o pior caso = comportamento atual (sem escala), mas agora auditável.

---

## 7. Repositório — `scripts_v2/servico_repositorio.py`

### 7.1 `periodos_para_linhas` — propagar as novas colunas
Incluir `valor_origem` e `escala_origem` em cada linha, com defaults defensivos:
```python
linhas.append({
    "cnpj": cnpj_norm,
    "data_ref": data_ref,
    "tipo_doc": tipo_doc,
    "demonstracao": demonstracao,
    "cd_conta": cd_conta,
    "ds_conta": conta.get("ds_conta"),
    "valor": conta.get("valor"),
    "valor_origem": conta.get("valor_origem", conta.get("valor")),
    "escala_origem": conta.get("escala_origem", "unidade"),
})
```
(Se a fonte não trouxe origem — legado —, `valor_origem = valor` e `escala_origem = 'unidade'`, mantendo a invariante.)

### 7.2 `salvar_demonstracoes` — nenhum ajuste estrutural
O `upsert` já manda o dict inteiro; as novas chaves entram automaticamente. `on_conflict` permanece `cnpj,data_ref,tipo_doc,demonstracao,cd_conta`. Confirmar que o `BATCH_SIZE` continua ok.

### 7.3 Leitura — expor as colunas
- `montar_demonstracoes_estruturadas`: no `_select_rows(...)` incluir `valor_origem,escala_origem`; e no dict de cada conta adicionar `"valor_origem"` e `"escala_origem"`.
- `listar_demonstracoes_financeiras`: adicionar `valor_origem,escala_origem` ao `.select(...)`.
- `montar_visao_completa_emissor`: se ela pré-carrega `rows` para passar a `montar_demonstracoes_estruturadas`, incluir as colunas no select dela também (procurar o `select` de `demonstracoes_financeiras` usado na visão completa).

---

## 8. API — `api/`
- Hoje as rotas de leitura devolvem dicts do repositório (sem Pydantic forte para as linhas de demonstração — `api/esquemas.py` não tipa `valor`). Portanto, **basta o repositório passar as colunas** (seção 7.3) que a API as expõe automaticamente em `/emissores/{cnpj}` e `/emissores/{cnpj}/visao-completa`.
- Se houver algum `response_model` que enumere campos de demonstração, adicionar `valor_origem: float | None` e `escala_origem: str | None`. (Conferir `api/esquemas.py` e `api/rotas_leitura.py`.)

---

## 9. Front — `frontend/`
Consumidores usam `valor` (reais cheios) — comportamento visual **melhora automaticamente** (magnitudes corretas). Ajustes:
- `frontend/lib/types.ts`: nas 3+ formas que têm `valor: number | string | null` (linhas ~58, ~71, ~223-225, ~269-271), adicionar campos opcionais:
  ```ts
  valor_origem?: number | string | null;
  escala_origem?: string | null;
  ```
- `frontend/components/financial-statements-table.tsx`: sem mudança funcional (usa `valor`). **Opcional (nice-to-have):** exibir um selo/tooltip com `escala_origem` ("origem: em milhares") por período, ou uma nota de rodapé. Não bloquear a entrega por isso.
- `frontend/components/asset-detail-panel.tsx` e `frontend/app/detalhe-emissor/[identificador]/page.tsx`: revisar formatação de moeda (agora reais cheios; garantir `Intl.NumberFormat('pt-BR', {notation:'compact'})` ou similar para não estourar a coluna).
- Rodar `./node_modules/.bin/tsc --noEmit` dentro de `frontend/`.

---

## 10. Dados existentes: **RE-INGESTÃO**, não backfill

⚠️ O `valor` legado está **corrompido pelo bug do separador** (o ponto decimal foi apagado) — a informação original **não é recuperável** por cálculo. Portanto:
- **Não** dá para "consertar" o legado com um `UPDATE` (não há como saber onde estava o decimal).
- O caminho é **re-ingerir**: usar a mecânica de remoção já existente (`servico_repositorio.deletar_dados_emissor` / CLI `scripts_v2/utils_remover_emissor.py`) e recadastrar o ticker (a etapa CVM repopula com o parser corrigido).
- Para o banco de teste: `python scripts_v2/utils_remover_emissor.py <CNPJ> --confirmar` e depois `POST /cadastro/ticker` novamente (ou o CLI `python scripts_v2/orquestrador.py ticker <TICKER>`).
- O `escala_origem='unidade'` do backfill (seção 4.1) só evita nulos em linhas legadas que sobrarem; assuma que as linhas boas virão da re-ingestão.

---

## 11. Precisão / tipos
- `demonstracoes_financeiras.valor` e `valor_origem` são `numeric` no Postgres → sem perda de precisão no armazenamento.
- Em Python, `valor_origem` vem como `float` (CVM) ou número do JSON (LLM). `float × 1000/1_000_000` é seguro para as magnitudes de DF (bem abaixo de 2^53). Se quiser rigor, converter para `int` quando o valor for inteiro, ou `Decimal`. **Não** usar `float` na coluna (já é `numeric`).

---

## 12. Regras de validação (sempre considerando escala)

Requisito do dono: **qualquer validação deve considerar a escala**. Como o `valor` canônico já está normalizado, a regra operacional é: **toda validação/sanity-check roda sobre `valor` (reais cheios), nunca sobre `valor_origem`.**

Adicionar (em um helper de validação, ex.: `scripts_v2/servico_ia_quantitativa.py` ou um novo `scripts_v2/validacao_demonstracoes.py`):
1. **Invariante de consistência:** para cada linha, `abs(valor - valor_origem * fator(escala_origem)) < 0.5` (detecta gravação incoerente).
2. **Enum de escala:** `escala_origem ∈ {unidade, mil, milhao}` (o CHECK do banco também garante).
3. **Sanity de magnitude (detecta o bug antigo):** alertar se `valor` de contas de topo (ex.: `cd_conta='1'` Ativo Total) exceder um teto absurdo (ex.: > 1e14) ou se, dentro de um mesmo `(cnpj, data_ref, demonstracao)`, houver contas com ordens de grandeza incompatíveis (indício de escala mista mal-lida).
4. Logar/emitir aviso (não precisa abortar) quando `escala_origem='unidade'` foi assumido por ausência de sinal (útil para revisar PDFs).

---

## 13. Extensões futuras (fora deste escopo, documentar)
- Coluna `moeda` (BRL/USD) — hoje assume-se BRL.
- `escala` por **demonstração** (não só por período) para docs que misturam escalas entre quadros.
- Painel/relatório de auditoria mostrando `valor_origem`+`escala_origem` lado a lado (encaixa no §8g "Gerenciar Dados").

---

## 14. Ordem de implementação (checklist)
1. [ ] Criar `scripts_v2/escala_moeda.py` (seção 3) + teste unitário.
2. [ ] Migração SQL 4.1 no Supabase + atualizar `supabase_schema_v2.sql` (4.2).
3. [ ] Corrigir `servico_cvm.parse_valor` + `processar_linhas` (seção 5).
4. [ ] Ajustar prompt + `extrair_quant_de_markdown` (seção 6).
5. [ ] `servico_repositorio`: `periodos_para_linhas` + leituras (seção 7).
6. [ ] API: expor colunas (seção 8) — provavelmente automático.
7. [ ] Front: tipos + formatação (seção 9); `tsc --noEmit`.
8. [ ] Helper/validações (seção 12).
9. [ ] Re-ingerir dados de teste (seção 10) e rodar os testes da seção 15.
10. [ ] Atualizar `HANDOVER.md` (marcar o bug de escala CVM da §8k como resolvido; documentar o modelo híbrido) e `AGENTS.md` se necessário.

---

## 15. Plano de testes (com números esperados)
**Unitário (`escala_moeda`):** `fator_escala('mil')==1000`; `para_reais(2326714,'mil')==2326714000`; `normalizar_escala('MIL')=='mil'`, `normalizar_escala('Em milhares de reais')=='mil'`.

**Unitário (CVM):** `parse_valor('2326714.0000000000')==2326714.0` (não 2.3e16).

**Integração CVM (Alares, cod_cvm 25194):** baixar ITR 2026, extrair BPA, para `DT_REFER=2026-06-30`, `ORDEM_EXERC` último, `CD_CONTA='1'`:
- `valor_origem == 2326714`, `escala_origem == 'mil'`, `valor == 2_326_714_000`.

**e2e (API + Supabase de teste):**
1. `python scripts_v2/utils_remover_emissor.py 23438929000100 --confirmar` (limpa Alares).
2. `POST /cadastro/ticker {"ticker":"ALAR14"}` → aguardar `concluido`.
3. `GET /emissores/23438929000100/visao-completa` → conferir Ativo Total 2026-06-30 ≈ `2.33e9` (não 2.3e16), com `escala_origem='mil'` e `valor_origem=2326714`.

**Quant (documento):** enviar um DF em Markdown com cabeçalho "em milhares de reais" → conferir que `escala_origem='mil'` e `valor` = número impresso × 1000.

---

## 16. Riscos / decisões travadas
- **Decisão travada:** `valor` canônico em **reais cheios**; **duas** colunas novas (`valor_origem`, `escala_origem`); mesma regra nas duas trilhas; validações sempre sobre `valor`.
- **Risco (LLM):** escala mal-lida de PDF → mitigado por `escala_origem` (corrigível sem re-ingestão) + sanity-check (seção 12).
- **Risco (legado):** dados antigos não são backfilláveis → **re-ingestão** (seção 10).
- **Não** introduzir `moeda` nem escala por-demonstração agora (seção 13).
- **Não** somar valores entre empresas (decisão do dono): comparações são intra-empresa, onde a escala é consistente — reforça que reais cheios canônico é seguro.
