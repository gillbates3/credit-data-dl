# Plano: Corrigir contraste do menu de abas (chrome verde)

> Spec autocontido para o agente executor. pt-BR. Windows. Frontend Next.js 16 + Tailwind v4.

## Context

No header verde (chrome) da aplicação, as abas **inativas** aparecem verdes sobre o fundo verde — invisíveis. Só a aba ativa ("Visão Geral", pílula cream) é vista. O regra correta é: como o chrome usa a **versão negativa** da marca (fundo Verde Serra), o **texto dos itens inativos deve ser Amarelo Palha (cream)**, nunca verde.

### Diagnóstico (importante — explica por que as tentativas anteriores "não pegam")

O arquivo em disco [frontend/components/app-nav.tsx](frontend/components/app-nav.tsx) **já está correto**: os itens inativos usam `text-[var(--chrome-ink)]` (cream `#fff0dc`), que tem alto contraste sobre `--chrome-bg` (`#0a2300`). O `cn()` em [lib/utils.ts](frontend/lib/utils.ts) é um `join` trivial (não descarta classes), e o [layout.tsx](frontend/app/layout.tsx) tem um único `<AppNav>`. Ou seja, **a fonte já produz o resultado certo**.

Logo, se a tela ainda mostra verde-no-verde, o sintoma corresponde a uma **versão antiga renderizada** — build/cache do Next defasado ou visualização de um `npm run start` de produção anterior às edições. Esse é o motivo provável de o Codex "consertar e continuar quebrado".

## Ação 1 — Destravar o build (provável causa real; fazer primeiro)

1. Parar o servidor do front.
2. Apagar o cache de build: remover a pasta `frontend/.next`.
3. Rodar **em modo dev** para garantir recompilação: em `frontend/`, `npm run dev`. (Se estiver validando produção, rodar `npm run build` e só então `npm run start` — nunca um `start` sobre build antigo.)
4. Recarregar o navegador com cache desabilitado (Ctrl+Shift+R).

Se as abas inativas aparecerem em cream legível, **está resolvido** — o resto é blindagem opcional, mas recomendada.

## Ação 2 — Blindar o nav com tokens semânticos (torna o intent inequívoco)

Para que nenhuma edição futura volte a pintar o texto inativo de verde, trocar os literais `rgba(255,240,220,…)` por tokens nomeados e fixar a regra de contraste.

### 2a. `frontend/app/globals.css` — adicionar ao `:root` (junto dos `--chrome-*`)
```css
--chrome-item-bg: rgba(255, 240, 220, 0.10);       /* fundo do item inativo */
--chrome-item-bg-hover: rgba(255, 240, 220, 0.20); /* hover */
--chrome-item-line: rgba(255, 240, 220, 0.30);     /* borda do item inativo */
```
(Reaproveitar `--chrome-ink` = cream para o texto inativo e o fundo ativo; `--accent` = verde para o texto ativo.)

### 2b. `frontend/components/app-nav.tsx` — usar os tokens, com a regra de contraste explícita
Regra inviolável: **inativo ⇒ texto `--chrome-ink` (cream)**; **ativo ⇒ fundo `--chrome-ink` + texto `--accent` (verde)**.
```tsx
className={cn(
  "rounded-full border px-4 py-2 text-sm font-medium transition",
  isActive
    ? "border-[var(--chrome-ink)] bg-[var(--chrome-ink)] text-[var(--accent)]"
    : "border-[var(--chrome-item-line)] bg-[var(--chrome-item-bg)] text-[var(--chrome-ink)] hover:bg-[var(--chrome-item-bg-hover)]",
)}
```
- Remover os `rgba(255,240,220,…)` inline atuais e o `shadow-[inset_…]` (opcional manter, mas em token se quiser).
- Não introduzir `text-[var(--accent)]`, `text-[var(--ink)]` nem `text-[var(--muted)]` nos itens — esses são verdes e somem no chrome.

## Verificação

1. Após a Ação 1, com a aba "/" ativa: as 4 abas (Visão Geral, Detalhe do Ativo, Detalhe do Emissor, Cadastro de Dados) devem estar **todas legíveis** em cream; a ativa é a pílula cream com texto verde.
2. Passar o mouse nos itens inativos → fundo clareia (hover), texto continua cream.
3. Navegar entre abas → o estado ativo migra corretamente.
4. `./node_modules/.bin/tsc --noEmit` em `frontend/` limpo; sem `text-[var(--accent)]`/`--ink`/`--muted` em [app-nav.tsx](frontend/components/app-nav.tsx).

## Fora de escopo
- Demais ajustes do tema Bocaina (cobertos por `front-estilo-bocaina.md`).
- Estrutura do header/logo (já correta no layout).
