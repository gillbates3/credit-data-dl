# Plano: Stepper visual de etapas (estilo metrô) no monitor de processo

> Spec autocontido para o agente executor (Codex). Assuma que ele **não** tem o histórico desta conversa. Idioma: **pt-BR**. Plataforma: **Windows**. Frontend Next.js 16 (App Router) + Tailwind v4 + TypeScript. Tema da marca **BOCAINA** (tokens em `frontend/app/globals.css`).

## Context

Na tela de acompanhamento de um cadastro ([frontend/components/process-monitor-client.tsx](frontend/components/process-monitor-client.tsx)), o card esquerdo mostra status, etapa atual e os metadados (Tipo/Alvo/Criado/Atualizado), mas **não há visão do progresso ao longo das etapas**: o usuário não sabe quantas etapas existem, quais já passaram nem quantas faltam. Há um espaço vazio no rodapé desse card.

Objetivo: adicionar um **stepper horizontal estilo "linha de metrô"** nesse espaço, com as etapas como estações que avançam conforme o pipeline progride (atualizado ao vivo pelo polling de 2s que já existe). Cada estação tem um **nome curto**; a estação ativa é destacada. É **puramente apresentação** — sem mudanças de backend, API, schema, rotas ou data-fetching.

## Decisões travadas (definidas pelo dono — não reabrir)

| Tema | Decisão |
|---|---|
| Orientação | **Horizontal** (estações da esquerda p/ direita, linha conectando os pontos, rótulo abaixo de cada ponto). |
| Rótulo da estação | **Nome curto** (ex.: "Identidade", "CVM", "Mercado"). A etapa ativa pode opcionalmente exibir a ação completa como legenda. |
| Posição | Rodapé do **card esquerdo** do monitor, abaixo do grid Tipo/Alvo/Criado/Atualizado. |
| Estilo | Tokens BOCAINA (verde `--accent`, cream, `--muted`, `--line`, `--danger`). Sem cores hardcoded. |
| Backend | **Sem alterações.** O fluxo e os estados são inferidos client-side dos dados que já chegam. |

## Dados disponíveis (client-side, em `ProcessRecord`)

Definido em [frontend/lib/types.ts](frontend/lib/types.ts). Relevantes:
- `status`: `pendente | rodando | concluido | concluido_com_erros | erro`.
- `etapa_atual`: enum estável gravado pelo orquestrador (string | null).
- `progresso.passos_concluidos`: **lista autoritativa** de etapas já concluídas (ex.: `["identidade", "cvm", "mercado"]`). Pode conter variantes de "pulado" (ex.: `"cvm_pulado"`).
- `alvo`: ticker (ex.: `CJEN13`) ou CNPJ (ex.: `01.115.535/0001-70`) — usado como fallback para inferir o fluxo.

**Dois fluxos, sequências disjuntas** (origem em `scripts_v2/orquestrador.py`, apenas referência — não alterar):
- **Ticker** (`ingerir_ticker`): `identidade → cvm → mercado`. A CVM é **pulada** em empresa Fechada (sem `cod_cvm`) → `passos_concluidos` contém `"cvm_pulado"`. Ao concluir, `etapa_atual` fica em `"mercado"`.
- **Documentos** (`ingerir_documentos`): `validacao_emissor → peek_hashes → ia_quant → ia_qual → finalizado`.

## Tarefa 1 — Lógica de etapas em `frontend/lib/process-monitor.ts`

Adicionar a definição dos fluxos e a função pura `computarEtapas`, reutilizando `isTerminalProcessStatus` (já existe no arquivo). Mantém a lógica testável e fora do componente.

```ts
import type { ProcessRecord } from "@/lib/types";

export type EstadoEtapa =
  | "concluida"
  | "pulada"
  | "atual"
  | "falhou"
  | "pendente";

export interface EstacaoProcesso {
  key: string;
  rotulo: string;
  estado: EstadoEtapa;
}

interface DefEstacao {
  key: string;            // valor de etapa_atual
  rotulo: string;         // nome curto da estação
  passoConcluido?: string; // chave em passos_concluidos, se diferente de `key`
  passoPulado?: string;    // chave de "pulada" em passos_concluidos
}

const FLUXO_TICKER: DefEstacao[] = [
  { key: "identidade", rotulo: "Identidade" },
  { key: "cvm", rotulo: "CVM", passoPulado: "cvm_pulado" },
  { key: "mercado", rotulo: "Mercado" },
];

const FLUXO_DOCUMENTOS: DefEstacao[] = [
  { key: "validacao_emissor", rotulo: "Validação" },
  { key: "peek_hashes", rotulo: "Duplicatas" },
  { key: "ia_quant", rotulo: "Extração (IA)" },
  { key: "ia_qual", rotulo: "Transcrição (IA)" },
  { key: "finalizado", rotulo: "Conclusão" },
];

function definirFluxo(process: ProcessRecord): DefEstacao[] {
  const etapa = process.etapa_atual?.trim().toLowerCase();
  if (etapa) {
    if (FLUXO_TICKER.some((e) => e.key === etapa)) return FLUXO_TICKER;
    if (FLUXO_DOCUMENTOS.some((e) => e.key === etapa)) return FLUXO_DOCUMENTOS;
  }
  // Fallback: alvo com 14 dígitos parece CNPJ → fluxo de documentos.
  const digitos = (process.alvo ?? "").replace(/\D/g, "");
  return digitos.length >= 14 ? FLUXO_DOCUMENTOS : FLUXO_TICKER;
}

export function computarEtapas(process: ProcessRecord): EstacaoProcesso[] {
  const fluxo = definirFluxo(process);
  const etapa = process.etapa_atual?.trim().toLowerCase() ?? null;
  const passos = Array.isArray(process.progresso?.passos_concluidos)
    ? (process.progresso!.passos_concluidos as string[]).map((p) =>
        p.toLowerCase(),
      )
    : [];
  const terminal = isTerminalProcessStatus(process.status);
  const falhou = process.status === "erro";
  const idxAtual = fluxo.findIndex((e) => e.key === etapa);

  return fluxo.map((est, idx) => {
    const pulado = !!est.passoPulado && passos.includes(est.passoPulado);
    const concluido = passos.includes(est.passoConcluido ?? est.key);

    let estado: EstadoEtapa;
    if (pulado) {
      estado = "pulada";
    } else if (concluido) {
      estado = "concluida";
    } else if (falhou && est.key === etapa) {
      estado = "falhou";
    } else if (terminal) {
      // Processo terminou: o que veio até a etapa final conta como concluído.
      estado = idxAtual >= 0 && idx <= idxAtual ? "concluida" : "pendente";
    } else if (est.key === etapa) {
      estado = "atual";
    } else if (idxAtual < 0 && idx === 0) {
      // Sem etapa definida ainda (pendente recém-criado): destaca a 1ª.
      estado = "atual";
    } else if (idxAtual >= 0 && idx < idxAtual) {
      // Fallback caso passos_concluidos venha vazio.
      estado = "concluida";
    } else {
      estado = "pendente";
    }

    return { key: est.key, rotulo: est.rotulo, estado };
  });
}
```

## Tarefa 2 — Componente `frontend/components/process-stepper.tsx`

Componente de apresentação puro (sem hooks; renderiza a partir de `process`). Horizontal, com conectores entre as estações. Mapear `estado → estilo` com tokens BOCAINA.

```tsx
import {
  computarEtapas,
  type EstadoEtapa,
} from "@/lib/process-monitor";
import type { ProcessRecord } from "@/lib/types";

const estiloDot: Record<EstadoEtapa, string> = {
  concluida: "border-[var(--accent)] bg-[var(--accent)] text-[var(--on-accent)]",
  pulada:
    "border-dashed border-[var(--line-strong)] bg-[var(--panel)] text-[var(--muted)]",
  atual:
    "border-[var(--accent)] bg-white text-[var(--accent)] ring-2 ring-[color-mix(in_srgb,var(--accent)_25%,transparent)] animate-pulse",
  falhou: "border-[var(--danger)] bg-[var(--danger)] text-white",
  pendente: "border-[var(--line)] bg-white text-[var(--muted)]",
};

function icone(estado: EstadoEtapa): string {
  if (estado === "concluida") return "✓";
  if (estado === "pulada") return "–";
  if (estado === "falhou") return "✕";
  if (estado === "atual") return "●";
  return "";
}

const COMPLETAS: EstadoEtapa[] = ["concluida", "pulada"];

export function ProcessStepper({ process }: { process: ProcessRecord }) {
  const estacoes = computarEtapas(process);
  if (estacoes.length === 0) return null;

  return (
    <div className="mt-6 rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-4">
      <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">
        Etapas
      </p>
      <ol className="mt-4 flex items-start">
        {estacoes.map((est, i) => {
          const primeiro = i === 0;
          const ultimo = i === estacoes.length - 1;
          const conectorEsq =
            !primeiro && COMPLETAS.includes(estacoes[i - 1].estado);
          const conectorDir = COMPLETAS.includes(est.estado);
          return (
            <li
              key={est.key}
              className="flex flex-1 flex-col items-center"
              aria-label={`${est.rotulo}: ${est.estado}`}
            >
              <div className="flex w-full items-center">
                <span
                  className={`h-0.5 flex-1 ${primeiro ? "opacity-0" : conectorEsq ? "bg-[var(--accent)]" : "bg-[var(--line)]"}`}
                />
                <span
                  className={`flex h-7 w-7 items-center justify-center rounded-full border text-xs font-semibold ${estiloDot[est.estado]}`}
                >
                  {icone(est.estado)}
                </span>
                <span
                  className={`h-0.5 flex-1 ${ultimo ? "opacity-0" : conectorDir ? "bg-[var(--accent)]" : "bg-[var(--line)]"}`}
                />
              </div>
              <span
                className={`mt-2 text-center text-xs ${est.estado === "atual" ? "font-semibold text-[var(--ink)]" : "text-[var(--muted)]"}`}
              >
                {est.rotulo}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
```

> O `ring-[color-mix(...)]` cria o halo da estação ativa a partir do verde da marca. Se preferir simplicidade, trocar por `ring-2 ring-[var(--line-strong)]`. Manter `animate-pulse` só na estação `atual`.

## Tarefa 3 — Inserir no monitor

Em [process-monitor-client.tsx](frontend/components/process-monitor-client.tsx), importar o componente e renderizá-lo **dentro do card esquerdo**, logo **após o `</dl>`** do grid de metadados (hoje termina por volta da linha 176) e **antes do `</div>`** que fecha o card esquerdo (~linha 177):

```tsx
import { ProcessStepper } from "@/components/process-stepper";
// ...
          </dl>

          <ProcessStepper process={process} />
        </div>  {/* fim do card esquerdo */}
```

Como `process` é atualizado pelo polling (`setProcess`), o stepper re-renderiza sozinho a cada leitura — sem estado próprio.

## Estados visuais (resumo)

| Estado | Ponto | Cor | Conector à esquerda |
|---|---|---|---|
| `concluida` | ✓ preenchido | verde `--accent`, texto cream | verde |
| `pulada` | – tracejado | borda tracejada `--line-strong`, fundo cream, texto `--muted` | verde (passou) |
| `atual` | ● com halo pulsante | borda verde, fundo branco, `animate-pulse` | verde até aqui |
| `falhou` | ✕ | `--danger` | verde até aqui |
| `pendente` | vazio | borda `--line`, fundo branco | cinza `--line` |

## Verificação

1. **Type-check**: em `frontend/`, `./node_modules/.bin/tsc --noEmit` sem erros.
2. **Build** (opcional): `npm run build` em `frontend/`.
3. **Visual ao vivo** (subir `uvicorn api.main:app --port 8000` na raiz + `npm run dev` em `frontend/`):
   - **Ticker, empresa Aberta**: cadastrar um ticker e abrir o monitor → o stepper avança Identidade → CVM → Mercado; a estação ativa pulsa; ao concluir, todas ficam ✓.
   - **Ticker, empresa Fechada** (ex.: `CJEN13`/TESC): a estação **CVM** aparece como **pulada** (tracejada), e Identidade/Mercado concluídas. (Casa com `progresso.passos_concluidos` contendo `cvm_pulado`.)
   - **Upload de documentos**: abrir o monitor de um processo de documentos → stepper mostra Validação → Duplicatas → Extração (IA) → Transcrição (IA) → Conclusão.
   - **Erro**: forçar um ticker inválido → a estação onde falhou aparece com ✕ (`falhou`) e o restante pendente.
4. **Sem dados de passos**: se `passos_concluidos` vier vazio, o stepper ainda posiciona corretamente pela `etapa_atual` (fallback por índice).

## Fora de escopo

- Qualquer alteração no backend / `orquestrador.py` / nomes de enum de `etapa_atual`.
- Mudanças no card direito ("Leituras de progresso") e na seção de erros.
- Persistir histórico/timestamps por etapa (o backend não expõe tempo por etapa hoje).
- Animações elaboradas além do `animate-pulse` da estação ativa.

## Dependência

Independente do plano `humanizar-rotulos-processo.md` (rótulos descritivos de `tipo`/`etapa`/desfecho), mas combina bem com ele: aquele cuida do texto do card "ETAPA ATUAL"; este, da régua de progresso. Podem ser implementados em qualquer ordem.
