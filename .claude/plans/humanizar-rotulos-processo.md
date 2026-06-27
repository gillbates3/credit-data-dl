# Plano: Humanizar rótulos de processo no frontend (tipo, etapa, desfecho)

> Spec autocontido para o agente executor (Codex). Assuma que ele **não** tem o histórico desta conversa. Idioma: **pt-BR**. Plataforma: **Windows**. Frontend Next.js 16 (App Router) + Tailwind v4 + TypeScript.

## Context

Na tela de acompanhamento de cadastro (monitor de processo) e na tabela de processos recentes, campos de **controle/enum** gravados em minúsculo pelo backend aparecem crus e confusos para o operador:

1. **`tipo`** e **`etapa_atual`** apareciam em minúsculo (`cadastro`, `identidade`, `mercado`), destoando do resto da UI.
2. Os nomes de **etapa** são identificadores de implementação (`mercado`, `cvm`, `peek_hashes`) que **não dizem nada** ao usuário de negócio.
3. Quando o processo **termina**, o card "ETAPA ATUAL" mostra a última etapa técnica que rodou (ex.: **"Mercado"** num processo já **CONCLUÍDO**) — enganoso: o usuário lê "Mercado" e não percebe que acabou.

Objetivo: traduzir esses enums para **linguagem de negócio na camada de apresentação**, sem tocar no backend. O `etapa_atual`/`status`/`tipo` continuam sendo os enums estáveis que o pipeline grava; o front mapeia para texto humano. É puramente apresentação — **sem mudanças de funcionalidade, rotas, data-fetching, contratos de API ou schema**.

## Decisões travadas (definidas pelo dono — não reabrir)

| Tema | Decisão |
|---|---|
| Capitalização de enums | Campos de controle (`tipo`, `etapa_atual`) em **sentence-case** (1ª letra maiúscula), com `_` virando espaço. |
| Acrônimos | Expandir siglas conhecidas em caixa-alta (`cvm`→**CVM**, `ia`→**IA**) via mapa, em vez de "Cvm"/"Ia". |
| Rótulos de etapa | **Descritivos da ação em andamento (gerúndio)**, sucintos, com acrônimos para caber no card. Ex.: "Identificando emissor na ANBIMA", "Acessando DFs na CVM". |
| Etapa de processo encerrado | Quando `status` é terminal (`concluido`/`concluido_com_erros`/`erro`), mostrar o **desfecho** ("Concluído" / "Concluído com avisos" / "Falhou") em vez da etapa técnica. |
| Status badges | **NÃO mexer.** Já são caixa-alta via CSS (`uppercase`) e estão consistentes. |
| Campos fora do escopo | **NÃO** capitalizar nomes próprios, tickers, ISIN, CETIP nem ratings (ex.: `brAAA` não pode virar `BrAAA`). Por isso o helper é dedicado, não o `formatText` genérico. |

## Tarefa 1 — Helpers em `frontend/lib/format.ts`

Adicionar **após** a função `formatText` existente. Três blocos: o `formatRotulo` (sentence-case + acrônimos) e o `rotuloEtapaProcesso` (rótulo de etapa + desfecho).

```ts
// Acrônimos que devem aparecer em caixa-alta (não só com a 1ª letra maiúscula).
// Chave em minúsculo; comparação token a token. Estender conforme necessário.
const ACRONIMOS_ROTULO: Record<string, string> = {
  cvm: "CVM",
  ia: "IA",
  cnpj: "CNPJ",
  isin: "ISIN",
};

// Formata rótulos de controle/enum gravados em minúsculo pelo pipeline
// (ex.: tipo, etapa_atual): troca "_" por espaço, expande acrônimos conhecidos
// (cvm → CVM) e deixa a 1ª letra maiúscula. NÃO usar em nomes próprios,
// tickers, ISIN ou ratings (ex.: "brAAA").
export function formatRotulo(value: string | null | undefined): string {
  const text = value?.trim();
  if (!text) {
    return "—";
  }

  const palavras = text.split(/[\s_]+/).map((palavra, indice) => {
    const minuscula = palavra.toLowerCase();
    if (ACRONIMOS_ROTULO[minuscula]) {
      return ACRONIMOS_ROTULO[minuscula];
    }
    if (indice === 0) {
      return minuscula.charAt(0).toUpperCase() + minuscula.slice(1);
    }
    return minuscula;
  });

  return palavras.join(" ");
}

// Rótulos descritivos (da ação em andamento) para cada etapa do pipeline.
// A chave é o enum estável que o orquestrador grava em `etapa_atual`.
const ETAPA_ROTULOS: Record<string, string> = {
  // Fluxo de cadastro por ticker
  identidade: "Identificando emissor na ANBIMA",
  cvm: "Acessando DFs na CVM",
  mercado: "Acessando características na ANBIMA",
  // Fluxo de upload de documentos (PDFs)
  validacao_emissor: "Validando emissor",
  peek_hashes: "Verificando duplicatas",
  ia_quant: "Extraindo DFs dos PDFs (IA)",
  ia_qual: "Transcrevendo PDFs (IA)",
  finalizado: "Finalizando",
};

// Quando o processo já terminou, a "etapa atual" mostra o desfecho — não a
// última etapa técnica que rodou (que confunde, ex.: "Mercado" num concluído).
const STATUS_DESFECHO: Record<string, string> = {
  concluido: "Concluído",
  concluido_com_erros: "Concluído com avisos",
  erro: "Falhou",
};

// Texto humano para o card/coluna "Etapa atual" de um processo.
export function rotuloEtapaProcesso(
  etapa: string | null | undefined,
  status: string | null | undefined,
): string {
  const desfecho = status ? STATUS_DESFECHO[status.trim().toLowerCase()] : undefined;
  if (desfecho) {
    return desfecho;
  }
  const chave = etapa?.trim().toLowerCase();
  if (!chave) {
    return "—";
  }
  return ETAPA_ROTULOS[chave] ?? formatRotulo(etapa);
}
```

> **Referência dos enums** (origem em `scripts_v2/orquestrador.py`, para conferência — não alterar o backend):
> - Fluxo **ticker** (`ingerir_ticker`): `etapa_atual` ∈ `identidade` → `cvm` → `mercado`. Ao concluir, o código deixa `etapa_atual="mercado"` com `status` terminal (daí a necessidade do desfecho).
> - Fluxo **documentos** (`ingerir_documentos`): `etapa_atual` ∈ `validacao_emissor` → `peek_hashes` → `ia_quant` → `ia_qual` → `finalizado`.

## Tarefa 2 — Aplicar nos call sites (apresentação)

Trocar o formatador em cada ponto que renderiza `tipo` ou `etapa_atual`. **`alvo` (ticker/CNPJ) permanece com `formatText`** — não capitalizar.

| Arquivo | Campo exibido | Formatador alvo |
|---|---|---|
| [process-monitor-client.tsx](frontend/components/process-monitor-client.tsx) | `process.tipo` (card **TIPO**) | `formatRotulo(process.tipo)` |
| [process-monitor-client.tsx](frontend/components/process-monitor-client.tsx) | `process.etapa_atual` (card **ETAPA ATUAL**) | `rotuloEtapaProcesso(process.etapa_atual, process.status)` |
| [process-monitor-client.tsx](frontend/components/process-monitor-client.tsx) | `process.alvo` | **manter** `formatText` |
| [recent-processes-table.tsx](frontend/components/recent-processes-table.tsx) | `process.tipo` (coluna **Tipo**) | `formatRotulo(process.tipo)` |
| [page.tsx](frontend/app/page.tsx) | `item.tipo` (rótulo cinza da debênture no portfólio, ex.: `debenture`→**Debenture**) | `formatRotulo(item.tipo)` |
| [asset-detail-panel.tsx](frontend/components/asset-detail-panel.tsx) | `caracteristicas.tipo` (campo **Tipo** do dossiê) | `formatRotulo(caracteristicas.tipo)` |

> A coluna **Etapa atual** da tabela de processos recentes **não** recebe formatador novo — ela é **removida** (ver Tarefa 2b). Só o card detalhado (process-monitor) mantém a "Etapa atual" com `rotuloEtapaProcesso`.

Atualizar os `import { … } from "@/lib/format";` de cada arquivo para incluir `formatRotulo` e/ou `rotuloEtapaProcesso` conforme o uso. Em `process-monitor-client.tsx`, ambos os helpers são usados; em `recent-processes-table.tsx`, apenas `formatRotulo` (o `rotuloEtapaProcesso` deixa de ser usado lá após a Tarefa 2b).

## Tarefa 2b — Remover a coluna "Etapa atual" da tabela de processos recentes

Em [recent-processes-table.tsx](frontend/components/recent-processes-table.tsx), a tabela é um **histórico** (quase todas as linhas terminais). Depois que a "Etapa atual" passou a mostrar o desfecho quando terminal (`Concluído`, `Concluído com avisos`, `Falhou`), a coluna virou **eco do STATUS** — informação repetida. Decisão do dono: **remover a coluna `Etapa atual`** e manter apenas **Status**.

- Excluir o objeto de coluna `{ key: "etapa", header: "Etapa atual", render: … }` do array `columns`.
- Remover `rotuloEtapaProcesso` do import de `@/lib/format` neste arquivo (passa a usar só `formatDateTime` e `formatRotulo`).
- Colunas finais: **Alvo · Tipo · Status · Atualizado em**.

> O card detalhado do monitor (`process-monitor-client.tsx`) **mantém** a "Etapa atual" — lá ela não é redundante (mostra a ação em andamento ao vivo) e ganha o stepper de etapas (plano `stepper-etapas-processo.md`).

> **Não** trocar `formatText` em campos de nome próprio/código/rating (nomes de emissor, indexador, ratings, ISIN, CETIP, ticker_acao etc.) — esses continuam em `formatText`.
> O `markdown-viewer.tsx` usa um mapa próprio (`markdownTypeLabel`) para o tipo de documento → **fora do escopo**.

## Estado atual do working tree (reconciliação)

Parte desta mudança **já foi aplicada** ao working tree nesta sessão; o executor deve garantir o estado-alvo acima (idempotente). Já aplicado:
- `frontend/lib/format.ts`: os 3 blocos da Tarefa 1 **já existem**.
- `process-monitor-client.tsx`: `process.tipo` já usa `formatRotulo`. **Falta**: trocar `etapa_atual` (hoje `formatText`) por `rotuloEtapaProcesso(process.etapa_atual, process.status)` e adicionar `rotuloEtapaProcesso` ao import.
- `recent-processes-table.tsx`: `tipo` já usa `formatRotulo`. **Falta**: **remover a coluna `Etapa atual`** (Tarefa 2b) e remover `rotuloEtapaProcesso` do import. (O `etapa_atual` hoje ainda renderiza nessa tabela; a coluna sai por inteiro.)
- `page.tsx`: `item.tipo` já usa `formatRotulo`.
- `asset-detail-panel.tsx`: `caracteristicas.tipo` já usa `formatRotulo`.

Em checkout limpo (sem essas edições), aplicar tudo do zero conforme Tarefas 1 e 2.

## Verificação

1. **Type-check**: em `frontend/`, `./node_modules/.bin/tsc --noEmit` → sem erros.
2. **Build** (opcional): em `frontend/`, `npm run build` sem erros.
3. **Visual** (subir API `uvicorn api.main:app --port 8000` na raiz + `npm run dev` em `frontend/`):
   - Cadastrar um ticker e abrir o monitor: durante o processo, ETAPA ATUAL mostra "Identificando emissor na ANBIMA" → "Acessando DFs na CVM" → "Acessando características na ANBIMA". Ao **concluir**, ETAPA ATUAL mostra **"Concluído"** (não "Mercado"); se houve avisos, "Concluído com avisos"; se falhou, "Falhou".
   - Card **TIPO**: "Cadastro" (1ª maiúscula).
   - Tabela de **processos recentes**: **sem** coluna "Etapa atual" (colunas: Alvo · Tipo · Status · Atualizado em); Tipo em sentence-case ("Cadastro").
   - Portfólio (`/`): rótulo da debênture "Debenture" (não "debenture").
   - Dossiê do ativo: campo Tipo "Debenture".
4. **Sem regressão de acrônimos**: uma etapa desconhecida cai no `formatRotulo` (fallback), expandindo `cvm`/`ia` se presentes.

## Fora de escopo

- Backend / `orquestrador.py` / nomes dos enums de `etapa_atual` (manter estáveis).
- `status-badge.tsx` (badges permanecem caixa-alta).
- Campos de nome próprio/código/rating em `formatText`.
- Mapa de tipo de documento do `markdown-viewer.tsx`.
