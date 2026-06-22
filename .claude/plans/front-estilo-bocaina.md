# Plano: Refactor de estilo do Frontend → Identidade de Marca BOCAINA

> **Entrega:** este documento é o spec autocontido para um agente executor (Codex). Assuma que ele **não** tem o histórico desta conversa. Idioma do projeto: **pt-BR**. Plataforma: **Windows**.

## Context

O frontend (`frontend/`, Next.js 16 App Router + Tailwind v4) está **funcionalmente pronto**, mas o estilo é genérico e **fora da marca**: paleta *teal + slate*, glassmorphism (cards `bg-white/74` + `backdrop-blur`, cantos `2rem`, sombras `rgba(15,23,42,…)`), fundo com gradiente turquesa + textura de scanlines, e fontes **IBM Plex Sans/Mono**. Nada disso respeita o **Guia de Identidade BOCAINA** (set/2020).

O objetivo é um **redesign visual completo** que faça o app respeitar a marca: paleta Verde Serra + Amarelo Palha, tipografia **Gotham HTF**, linguagem limpa/geométrica/editorial com respiro generoso, e o **logo/símbolo (pássaro)** aplicado no chrome. **Sem mudanças de funcionalidade, rotas, data-fetching ou contratos de API** — é puramente camada de apresentação (tokens, fontes, classes Tailwind, alguns componentes de UI).

A boa notícia: o código é **token-driven** — quase todos os componentes referenciam CSS vars (`var(--ink)`, `var(--muted)`, `var(--line)`, `var(--accent)`, `var(--panel)`…). Redefinir os tokens em [globals.css](frontend/app/globals.css) propaga a maior parte da mudança automaticamente. O resto é: trocar as fontes em [layout.tsx](frontend/app/layout.tsx), pintar o chrome de verde, e um passe focado nos poucos pontos com cor hardcoded.

## Decisões travadas (definidas pelo dono do produto — não reabrir)

| Decisão | Escolha |
|---|---|
| Tema-base | **Claro + cromo verde**: fundo Amarelo Palha (cream), conteúdo/cards em branco, **chrome (header + nav) em Verde Serra com texto/logo cream** (versão negativa da marca). |
| Profundidade | **Redesign completo**: trocar tokens + fontes **e** revisar a linguagem visual (remover glassmorphism, cantos menos arredondados/geométricos, sombras suaves esverdeadas, respiro/entrelinhas generosos, hierarquia tipográfica do guia). |
| Elementos decorativos | **Apenas logo + símbolo (pássaro)** no header e favicon. **NÃO** usar padronagens Tupi-Guarani nem motivos a 22,5° nesta rodada. |
| Tipografia | **Gotham HTF em tudo** (principal). Helvetica como fallback de sistema. **Não** usar New York (serifada) por enquanto — manter os arquivos disponíveis, mas não aplicar. |
| Inspiração | Site oficial https://bocainacapital.com/ — sans-serif, verde + cream, muito respiro, bordas mínimas, rótulos de seção numerados em caixa-alta (ex.: "01. TIME"). |

## Referência da marca (Guia de Identidade BOCAINA)

### Paleta (códigos cromáticos — usar HEX)
| Cor | HEX | Uso na marca |
|---|---|---|
| **Verde Serra Puro** | `#0a2300` | Cor principal. Texto, chrome, ações primárias. |
| **Verde Serra Escuro** | `#0a0f00` | Pequenos elementos editoriais, hover de verde, eventualmente fundos. |
| **Amarelo Palha Puro** | `#fff0dc` | Fundo principal (cream); texto/logo na versão negativa (sobre verde). |
| **Amarelo Palha Escuro** | `#f5e6cd` | Insets sutis, faixas, estados de superfície secundária. |
| **Marrom Semente** | `#cdaa82` | No guia é exclusivo p/ tratamento de imagem; **aqui** usaremos só como base de um tom semântico "atenção" discreto. |

Princípios: paleta **reduzida**, **alto contraste**, clareza. Proporção: cores puras (verde/cream) dominam; branco e tons escuros entram como apoio.

### Tipografia
- **Gotham HTF** (principal, sans): Títulos = Bold ou Light; Subtítulos = Light; Corpo = Book/Regular ou Light; Destaque = Bold.
- **Espaçamento entre letras**: o guia pede **tracking positivo/arejado** em títulos e subtítulos ("igual a 40", i.e. ~`+0.04em`). ⚠️ O código atual faz o **oposto** (`tracking-[-0.04em]`, apertado) — **inverter** para neutro/levemente positivo.
- **Entrelinhas generosas** ("respiro"): aumentar `line-height` de corpo e listas.
- Rótulos de seção em **caixa-alta + tracking largo** (já existe via `font-mono`; manter o padrão, mas renderizado em Gotham).
- Fallback de sistema: **Helvetica**, Arial, sans-serif.

### Fontes já presentes no repo
`frontend/fonts/`: `GothamHTF-Light.otf`, `GothamHTF-LightItalic.otf`, `GothamHTF-Book.otf`, `GothamHTF-BookItalic.otf`, `GothamHTF-Bold.otf`, `GothamHTF-BoldItalic.otf`, `GothamHTF-Ultra.otf`, `GothamHTF-UltraItalic.otf`, e as `NewYorkExtraLarge*` (não usar agora).

---

## Tarefa 1 — Tokens de design (`frontend/app/globals.css`)

Reescrever o bloco `:root` e o `body`. Esta é a mudança de maior alavancagem: a maioria dos componentes herda daqui.

### 1a. Novo `:root` (mapear os **mesmos nomes de token** já usados pelos componentes para valores da marca)
```css
:root {
  /* Fundo (tema claro / cream) */
  --bg: #fff0dc;            /* Amarelo Palha Puro — fundo da página */
  --bg-2: #fff7ea;          /* cream levemente mais claro p/ profundidade sutil */

  /* Superfícies */
  --panel: #f5e6cd;         /* Amarelo Palha Escuro — insets, header de tabela */
  --panel-strong: #f0dcb8;  /* cream mais saturado — estados ativos */

  /* Linhas / bordas (verde translúcido, no tom da marca) */
  --line: rgba(10, 35, 0, 0.12);
  --line-strong: rgba(10, 35, 0, 0.30);

  /* Tinta / texto */
  --ink: #0a2300;           /* Verde Serra Puro — texto principal */
  --muted: rgba(10, 35, 0, 0.60);  /* texto secundário no mesmo verde, esmaecido */

  /* Ações primárias */
  --accent: #0a2300;        /* Verde Serra Puro */
  --accent-strong: #0a0f00; /* Verde Serra Escuro (hover) */
  --on-accent: #fff0dc;     /* Amarelo Palha — texto sobre verde (substitui o branco) */

  /* Chrome (header + nav) — versão negativa da marca */
  --chrome-bg: #0a2300;
  --chrome-ink: #fff0dc;
  --chrome-muted: rgba(255, 240, 220, 0.66);
  --chrome-line: rgba(255, 240, 220, 0.18);

  /* Tons semânticos (badges, erros) — derivados, dentro da paleta */
  --success: #0a2300;  --success-bg: rgba(10, 35, 0, 0.08);    --success-line: rgba(10, 35, 0, 0.22);
  --info: #2f5d3a;     --info-bg: rgba(47, 93, 58, 0.10);      --info-line: rgba(47, 93, 58, 0.28);
  --warning: #6b4a26;  --warning-bg: rgba(205, 170, 130, 0.22); --warning-line: rgba(205, 170, 130, 0.55);
  --danger: #8a2b1e;   --danger-bg: rgba(138, 43, 30, 0.10);   --danger-line: rgba(138, 43, 30, 0.30);

  /* Sombras suaves esverdeadas (substituem rgba(15,23,42,…)) */
  --shadow-soft: 0 1px 2px rgba(10, 35, 0, 0.04), 0 10px 28px rgba(10, 35, 0, 0.05);
  --shadow-card: 0 1px 2px rgba(10, 35, 0, 0.05), 0 16px 44px rgba(10, 35, 0, 0.07);

  /* Raio (mais geométrico que os 2rem atuais) */
  --radius-card: 1rem;
  --radius-control: 0.625rem;
}
```

### 1b. `@theme` (Tailwind v4) — registrar Gotham como `sans` **e** `mono`
Assim **todas** as classes `font-mono` existentes (eyebrows, headers de tabela, badges) passam a renderizar em Gotham caixa-alta, sem precisar trocar classe a classe.
```css
@theme {
  --font-sans: var(--font-gotham), Helvetica, Arial, sans-serif;
  --font-mono: var(--font-gotham), Helvetica, Arial, sans-serif;
}
```

### 1c. `body` — remover gradiente turquesa e a textura de scanlines
- Trocar o `background` por fundo **cream sólido** (`var(--bg)`), opcionalmente um gradiente cream→cream-claro muito sutil.
- **Remover** o bloco `body::before` (scanlines) inteiro.
- Aumentar `line-height` base (ex.: `line-height: 1.6`) para o "respiro".

### 1d. `.nav-chip-link` e `::selection`
- `.nav-chip-link`: trocar todos os `rgba(15,123,115,…)` (teal) por verde da marca (`rgba(10,35,0,…)`); manter o formato pill, mas alinhar à nova paleta.
- `::selection`: `background: rgba(10, 35, 0, 0.15);`

---

## Tarefa 2 — Fontes e chrome (`frontend/app/layout.tsx`)

1. Remover os imports `IBM_Plex_Mono, IBM_Plex_Sans` de `next/font/google` e suas instâncias.
2. Adicionar `next/font/local` carregando Gotham a partir de `frontend/fonts/`:
```ts
import localFont from "next/font/local";

const gotham = localFont({
  variable: "--font-gotham",
  display: "swap",
  src: [
    { path: "../fonts/GothamHTF-Light.otf",       weight: "300", style: "normal" },
    { path: "../fonts/GothamHTF-LightItalic.otf",  weight: "300", style: "italic" },
    { path: "../fonts/GothamHTF-Book.otf",         weight: "400", style: "normal" },
    { path: "../fonts/GothamHTF-BookItalic.otf",   weight: "400", style: "italic" },
    { path: "../fonts/GothamHTF-Bold.otf",         weight: "700", style: "normal" },
    { path: "../fonts/GothamHTF-BoldItalic.otf",   weight: "700", style: "italic" },
    { path: "../fonts/GothamHTF-Ultra.otf",        weight: "800", style: "normal" },
  ],
});
```
3. `<html className={gotham.variable}>` e `<body className="font-sans antialiased">` (o `font-sans` resolve para Gotham via `@theme`).
4. **Chrome verde** no `<header>`:
   - `bg-[var(--chrome-bg)]`, texto cream; o eyebrow "Credit Data DL" e o `<h1>` passam a `text-[var(--chrome-muted)]` / `text-[var(--chrome-ink)]`.
   - Remover `bg-white/78` + `backdrop-blur` + sombra slate; o header vira bloco sólido Verde Serra (sticky ok). Raio `--radius-card`.
   - Inserir o **logo BOCAINA (versão negativa/cream)** à esquerda (ver Tarefa 6), substituindo ou acompanhando o título textual.
5. Atualizar `metadata.title` para a marca (ex.: `"BOCAINA · Mesa de Dados de Crédito"`).

---

## Tarefa 3 — Navegação (`frontend/components/app-nav.tsx`)

A nav vive dentro do chrome verde → estados **cream-sobre-verde** (negativa):
- Item **inativo**: `text-[var(--chrome-muted)]`, borda `var(--chrome-line)`, hover → `text-[var(--chrome-ink)]`.
- Item **ativo**: fundo cream (`bg-[var(--chrome-ink)]`) + texto verde (`text-[var(--accent)]`) — destacar com a cor pura.
- Manter `rounded-full`. Remover qualquer `bg-white/70`.

---

## Tarefa 4 — `status-badge.tsx` (única paleta hardcoded grande)

Substituir o `statusMap` (slate/sky/emerald/amber/rose/indigo/fuchsia) por classes que usam os **tokens semânticos** (Tarefa 1a). Mapeamento sugerido:

| status | token |
|---|---|
| `concluido`, `ativo` | success (verde) |
| `rodando`, `analise`/`análise` | info (verde médio) |
| `pendente`, `previsto` | neutro (`bg-[var(--panel-strong)]` + `text-[var(--muted)]`) |
| `concluido_com_erros`, `delta`, `qualitativo` | warning (marrom semente) |
| `erro` | danger |

Usar arbitrary values com tokens, ex.: success → `"border-[var(--success-line)] bg-[var(--success-bg)] text-[var(--success)]"`. Manter pill + caixa-alta + tracking.

---

## Tarefa 5 — Passe de polimento por componente (linguagem visual)

Mudanças repetidas em todos os arquivos de UI. Padrão a aplicar (buscar e substituir por componente, não linha a linha):

1. **Sombras**: trocar todas as `shadow-[0_…_rgba(15,23,42,…)]` por `shadow-[var(--shadow-card)]` (cards/seções) ou `shadow-[var(--shadow-soft)]` (elementos menores). ~33 ocorrências em ~17 arquivos (`app/**` e `components/**`).
2. **Raios**: `rounded-[2rem]`/`rounded-[1.75rem]` → `rounded-2xl` (1rem); insets internos → `rounded-xl` (0.75rem). Manter `rounded-full` em badges, botões e nav pills.
3. **Glassmorphism**: remover `backdrop-blur`; trocar `bg-white/74`,`/78`,`/88`,`/70`,`/75` por `bg-white` sólido (cards) ou `bg-[var(--panel)]` (insets cream). Cards brancos sobre cream já dão a separação.
4. **Texto em botões verdes**: `text-white` → `text-[var(--on-accent)]` (cream); spinner `border-white/35 border-t-white` → tons cream. Arquivos: [submit-button.tsx](frontend/components/submit-button.tsx), [identifier-search-form.tsx](frontend/components/identifier-search-form.tsx), [document-registration-form.tsx](frontend/components/document-registration-form.tsx) (inclui `file:text-white`), [asset-selector-combobox.tsx](frontend/components/asset-selector-combobox.tsx), [error.tsx](frontend/app/error.tsx).
5. **Erros**: `text-rose-700` → `text-[var(--danger)]` (5 arquivos: identifier-search-form, ticker-registration-form, asset-history-section, asset-selector-combobox, document-registration-form).
6. **Hover teal hardcoded** no combobox [asset-selector-combobox.tsx](frontend/components/asset-selector-combobox.tsx#L176-L178): trocar os `rgba(15,123,115,…)` por `rgba(10,35,0,…)`.
7. **Títulos**: nos headings grandes, trocar `tracking-[-0.04em]`/`tracking-[-0.03em]` (apertado) por `tracking-normal` ou levemente positivo (`tracking-[0.01em]`) — alinhado ao espaçamento arejado do guia. Eyebrows já corretos.
8. **Respiro**: garantir `leading-6`/`leading-7` em descrições e listas densas.

Arquivos a varrer: [page-header.tsx](frontend/components/page-header.tsx), [data-table.tsx](frontend/components/data-table.tsx), [empty-state.tsx](frontend/components/empty-state.tsx), [asset-detail-panel.tsx](frontend/components/asset-detail-panel.tsx), [financial-statements-table.tsx](frontend/components/financial-statements-table.tsx), [markdown-viewer.tsx](frontend/components/markdown-viewer.tsx), [asset-history-section.tsx](frontend/components/asset-history-section.tsx), [recent-processes-table.tsx](frontend/components/recent-processes-table.tsx), [process-monitor-client.tsx](frontend/components/process-monitor-client.tsx), e as páginas em [frontend/app/](frontend/app/) (`page.tsx`, `error.tsx`, `cadastro-dados/page.tsx`, `detalhe-ativo/page.tsx`, `detalhe-emissor/[identificador]/page.tsx`, `detalhe-emissor/page.tsx`).

> Como cards de KPI/seções usam `var(--panel)` e `bg-white`, ajustam-se sozinhos. Foco do passe manual: sombras, raios, glass, `text-white`, `text-rose-700` e teal hardcoded.

---

## Tarefa 6 — Assets de logo (`frontend/public/`)

Os PNGs **ainda não estão no repo** (não há pasta `public/`). Passos:

1. Criar `frontend/public/brand/`.
2. Salvar os arquivos fornecidos com nomes estáveis (referenciados no código):
   - `bocaina-logo-cream.png` — logo completo (pássaro + "BOCAINA") em **Amarelo Palha** → header verde.
   - `bocaina-logo-green.png` — logo completo em **Verde Serra** → uso futuro sobre cream.
   - `bocaina-symbol-cream.png` / `bocaina-symbol-green.png` — só o símbolo (pássaro).
   - Favicon: gerar do símbolo (`frontend/app/icon.png`, ~32–512px).
   > **Recomendado**: se possível, exportar **SVG** (nitidez/retina; o site oficial usa SVG no header). Havendo SVG, preferir `.svg` e ajustar nomes/extensões.
3. Header: inserir `<Image src="/brand/bocaina-logo-cream.svg" .../>` (ou `.png`) via `next/image`, `alt="BOCAINA"`, altura ~28–32px no lockup. Substituir/acompanhar o `<h1>` textual.
4. Favicon: `frontend/app/icon.png` (símbolo) — Next gera o `<link>` automaticamente.

---

## Verificação (end-to-end)

1. **Dev**: em `frontend/`, `npm run dev` (porta 3000). Para dados reais, subir `uvicorn api.main:app --port 8000` na raiz.
2. **Fontes** (DevTools → Network/Computed): **Gotham HTF** carrega e é aplicada a corpo, títulos e rótulos; nenhuma referência a IBM Plex; fallback Helvetica/Arial.
3. **Cores**: fundo `#fff0dc`, texto `#0a2300`, chrome `#0a2300` com texto `#fff0dc`. Nenhum teal (`#0f7b73`) ou slate (`rgba(15,23,42…)`) remanescente.
4. **Grep de regressão** (vazio em `app/` e `components/`): `rgba(15,23,42` · `0f7b73` / `rgba(15, 123` · `text-white` · `text-rose-` · `backdrop-blur` · `IBM_Plex` · `font-plex`.
5. **Contraste**: cream↔Verde Serra passa AA com folga (alto contraste é princípio da marca). Conferir badges e nav ativa.
6. **Visual por rota**: `/`, `/detalhe-ativo`, `/detalhe-emissor`, `/cadastro-dados` — header verde com logo cream, cards brancos sobre cream, botões verdes texto cream, badges semânticos, cantos mais geométricos, sem glass.
7. **Build**: `npm run build` (em `frontend/`) sem erros; `./node_modules/.bin/tsc --noEmit` limpo.

## Fora de escopo (não fazer agora)

- Qualquer mudança de funcionalidade, rotas, data-fetching, contratos de API, ou nos arquivos `lib/` (`api.ts`, `format.ts`, `types.ts`, `cnpj.ts`).
- Padronagens Tupi-Guarani e motivos a 22,5°.
- Fonte serifada New York (manter arquivos, não aplicar).
- Tema escuro alternável / preferências de usuário.
- Tratamento sépia de imagens (Marrom Semente / Color Burn) — não há imagens de conteúdo no app.
