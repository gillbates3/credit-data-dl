# AGENTS.md — guia para agentes de código neste repositório

> Ponto de entrada curto para agentes (Codex, Claude, etc.). A referência **canônica e detalhada** da arquitetura é [`.claude/plans/HANDOVER.md`](.claude/plans/HANDOVER.md) — leia-a antes de mexer no backend V2.

## O que é
`credit-data-dl`: pipeline de extração/consolidação de dados de **debêntures brasileiras** para análise de crédito. Semeadura por **ticker** → descobre emissor (CNPJ/ANBIMA) → CVM + mercado + upload de documentos → Supabase.

## Convenções
- **Idioma: pt-BR** em código, comentários, commits e docs.
- **Plataforma: Windows** (PowerShell + Bash disponíveis).
- **Planos** ficam em `.claude/plans/<nome-descritivo>.md` (versionados no Git). São **specs pontuais**: alguns estão marcados `⚠️ SUPERSEDED` — nesse caso vale o HANDOVER + o código, não o plano.
- **Env:** tudo em `.env` / `.env.local` na raiz (gitignored). Nunca commitar chaves. Chaves: `SUPABASE_URL`, `SUPABASE_KEY` (service_role), `GEMINI_API_KEY`, `JINA_API_KEY`, `API_KEY`.
- **Commits:** só quando pedido; nunca fazer push/merge sem autorização explícita.

## Arquitetura V2 (atual)
```
Front (Next.js, frontend/) → API (FastAPI, api/) → scripts_v2/orquestrador.py → serviços de coleta + servico_repositorio.py → Supabase
```
- **`scripts_v2/`** é o sistema atual. **`scripts/`** é o **V1 legado** (batch local) — referência apenas.
- **`servico_repositorio.py`** é a **única** camada que fala com o Supabase.
- **`orquestrador.py`** sequencia os serviços; a **API cria o job** e passa `process_id` (o orquestrador não cria jobs).
- Endpoints reais: `api/rotas_cadastro.py` (`/cadastro/*`) e `api/rotas_leitura.py` (`/processos`, `/portfolio`, `/agenda-eventos`, `/ativos*`, `/emissores*`).

## Conversão de documentos → Markdown (regra importante — §8k do HANDOVER)
Cada documento é convertido **uma vez** e o Markdown alimenta **as duas trilhas**:
- **PDF → Jina OCR** (`jina-ocr-v1`), em `servico_ocr_jina.py`. Sempre OCR-iza.
- **Não-PDF → Docling**, em `servico_docling.py`.
- Dispatcher: `servico_ia_qualitativa.extrair_markdown_documento`.
- **Quali** guarda o Markdown; **Quant** (`servico_ia_quantitativa.extrair_quant_de_markdown`) estrutura o **mesmo** Markdown → JSON CVM. O gate da quant é por **conteúdo** (`markdown_tem_sinais_financeiros`), não por nome de arquivo.
- **NÃO reintroduzir:** Gemini texto/Vision na conversão de PDF, nem filtro por nome na quant, nem `pdfplumber` como leitor primário. O Gemini permanece só para **título** e para a **estruturação quant** do Markdown.

## Como rodar / verificar
- API: `uvicorn api.main:app --port 8000` (raiz; precisa `.env`/`.env.local`).
- Orquestrador CLI: `python scripts_v2/orquestrador.py ticker PETR26` | `... docs <CNPJ> <pasta>`.
- Front: em `frontend/`, `npm run dev`; typecheck `./node_modules/.bin/tsc --noEmit`.
- Sempre validar sintaxe/import após editar Python: `python -m py_compile <arquivo>`.

## Remoção de dados por grupo econômico (CNPJ)
Mecânica de **hard delete** FK-safe (base do §8g). Em `servico_repositorio`: `deletar_dados_emissor(cnpj, incluir_emissor=True)` e `contar_dados_emissor(cnpj)`. CLI:
```bash
python scripts_v2/utils_remover_emissor.py <CNPJ>                    # dry-run (só conta)
python scripts_v2/utils_remover_emissor.py <CNPJ> --confirmar        # apaga tudo, inclusive o emissor
python scripts_v2/utils_remover_emissor.py <CNPJ> --confirmar --manter-emissor  # apaga só os dados
```
⚠️ É **destrutivo e no banco real**. Só rodar com autorização explícita do dono.
