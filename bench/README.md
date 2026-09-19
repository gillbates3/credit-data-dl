# bench/ — Benchmark de parsers de documentos (PDF → Markdown)

Avaliação de motores de ingestão documental para o pipeline de análise de crédito
(`credit-data-dl`), com foco em substituir o caminho atual `pdfplumber` + Gemini Vision
por um parser local que entregue Markdown denso e tabelas de DF fiéis.

Candidatos testados: **Docling** (IBM, MIT), **Marker** (Datalab), **MinerU** (OpenDataLab).

## Por que este benchmark existe

O pipeline atual (`scripts_v2/servico_ia_qualitativa.py`, `servico_ia_quantitativa.py`)
extrai texto com `pdfplumber` (que corrompe tabelas) e cai para Gemini Vision em PDFs
escaneados (caro). A hipótese é usar um parser local com reconhecimento de tabela +
OCR para gerar:
- **trilha qualitativa**: Markdown denso como fonte de verdade;
- **trilha quantitativa**: tabelas CVM já estruturadas (`cd_conta / ds_conta / valor`).

## Resultados até aqui

### PDF sintético com gabarito (`fixtures/df_sintetica.pdf`, 66 células conhecidas)
| Parser | Fidelidade (valores) | Estrutura da tabela | Tempo (CPU, cold) | Observação |
|---|---|---|---|---|
| Docling | 66/66 (100%) | ✅ totais dentro da tabela | 52 s | pip puro, roda em CPU |
| Marker | 66/66 (100%) | ✅ totais dentro da tabela | 26 s | ~2× mais rápido em texto nato |
| MinerU 4.x (tier `flash`) | 66/66 valores | ⚠️ "Total do ativo" descolado da tabela | — | engine bom exige parse-server VLM/GPU |

> O sintético é um **piso**: por ter camada de texto, todos acertam os números. O que
> diferencia é a **estrutura** (e o custo de operação de cada um).

### Documentos reais — head-to-head Docling × Marker (CONCLUÍDO, CPU)
Fechado localmente (desktop Windows 11, **CPU-only, sem GPU NVIDIA**) após instalar o binário
`llama-server` que faltava na nuvem. Versões: docling 2.129.0, marker-pdf 2.0.0, surya-ocr 0.22.1,
llama.cpp build b11056 (win-cpu-x64). Os `.md` estão em `outputs/reais/` (`*.docling.md` / `*.marker.md`).

| Caso | Métrica | Docling | Marker | Vencedor |
|---|---|---|---|---|
| `alares_3` DF CVM (6 pág, digital) | tempo | 155,3 s (25,9 s/pág) | **90,3 s (15,1 s/pág)** | Marker |
| | estrutura `cd_conta` | hierarquia OK, mas **~6 células com code-bleed** (cód. vaza p/ descrição; ex. `2.01.03.01.01 Imposto de \| Renda…`) | **coluna `cd_conta` 100% limpa, 0 glitches** | **Marker** |
| | valores / períodos | 3 períodos alinhados, totais na tabela | idênticos (mesmos 756 `\|`), totais na tabela | empate |
| | detalhe | preserva subtítulo "(Reais Mil)" | omite "(Reais Mil)" | Docling (menor) |
| `ot_2` ata (4 pág, **escaneado/OCR**) | tempo | **159,7 s (39,9 s/pág)** | 934,7 s (233,7 s/pág, ~6×) | Docling |
| | fidelidade OCR | **degrada grave**: perde a cláusula (I) da Ordem do Dia, ref. "Resolução CVM 81" e "art. 76 §2º" viram lixo (`o o oo o oro…`); erros de caixa | **transcrição fiel** do texto jurídico, incl. cláusula (I) inteira, `US$100.000.000,00`, negrito/itálico e assinaturas | **Marker** |
| `alares_1` deck (digital, gráficos) | números em gráficos | não saem | não saem (VLM de chart desligado) | empate (limite universal) |

**Veredito:**
- **DF estruturada (`alares_3`): Marker SUPERA o Docling** — mesma hierarquia e valores, porém sem os
  glitches de code-bleed do Docling, e ~40% mais rápido. Mapeia direto p/ `cd_conta/ds_conta/valor`.
- **OCR de escaneado (`ot_2`): Marker SUPERA em qualidade, mas PERDE em custo** — o VLM `surya-ocr-2`
  recupera trechos que o OCR do Docling destrói (crítico p/ crédito: sem a cláusula (I) a ata é inútil),
  ao custo de **~6× mais tempo em CPU**. Numa máquina com GPU o tempo do Marker cairia drasticamente.
- **Deck (`alares_1`): empate** — nenhum parser lê números dentro de gráficos sem VLM de chart.

> **Recomendação operacional:** Marker é o melhor motor de qualidade para DFs e escaneados. Em CPU,
> o OCR VLM do Marker é caro (~4 min/pág aqui pode variar); considere Docling como fallback rápido em
> escaneados de baixa criticidade, ou rodar Marker em GPU. Para DFs digitais, Marker é melhor e mais rápido.

### Nota: MinerU nos reais (não executado)
MinerU 4.x exige **parse-server VLM (GPU/vLLM)**; este desktop não tem GPU NVIDIA, então ficou fora do
head-to-head dos reais (o resultado do sintético em `outputs/sintetico/` permanece como referência).

## Como rodar

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-bench.txt
```

### Marker: instalar o binário `llama-server` (passo que faltava)
```bash
# macOS
brew install llama.cpp
# Linux: baixe o release ubuntu-x64 de https://github.com/ggml-org/llama.cpp/releases
#        e ponha `llama-server` no PATH, OU:
export LLAMA_CPP_BINARY=/caminho/para/llama-server
# Windows (testado, funciona): baixe o asset `llama-<build>-bin-win-cpu-x64.zip`
#   de https://github.com/ggml-org/llama.cpp/releases (build b11056 validada),
#   extraia e ponha a pasta no PATH, OU: set LLAMA_CPP_BINARY=C:\...\llama-server.exe
llama-server --version   # deve responder sem erro
```

> Como o surya localiza o binário (surya 0.22.1): `settings.LLAMA_CPP_BINARY` (default `llama-server`)
> resolvido via `shutil.which` → basta estar no PATH. Na 1ª execução com OCR, o surya **baixa
> sozinho** o GGUF `datalab-to/surya-ocr-2-gguf` (modelo + mmproj) do HF e sobe o `llama-server`
> como servidor VLM local. A build b11056 rodou sem o bug de grammar `\d` (issue surya #542).

### Baixar os PDFs de teste (não versionados; terceiros)
Salve em `pdfs/`:
- `alares_1.pdf` (deck): `https://api.mziq.com/mzfilemanager/v2/d/f1cecb7e-dccd-4943-9d90-f75514c92504/7afd8305-8d72-8ebb-7f17-3147839a27a4?origin=2`
- `alares_3.pdf` (DF CVM): `https://api.mziq.com/mzfilemanager/v2/d/f1cecb7e-dccd-4943-9d90-f75514c92504/14030293-2350-1f29-11a4-874e22faf850?origin=2`
- `ot_3.pdf` (relatório AF, 108 pág): `https://api-site.oliveiratrust.com.br/scot/Arquivos/AF-1483/1666381-34721-20230505131557.pdf`
- `ot_2_scan.pdf` (ata escaneada, OCR): `https://api-site.oliveiratrust.com.br/scot/Arquivos/AF-1483/1977231-34721-20240918150350.pdf`

### Executar
```bash
mkdir -p out
# DF real da CVM (Docling 1-indexado inclusivo; Marker 0-indexado)
python run_docling.py pdfs/alares_3.pdf out/alares_3.docling.md 3-8
python run_marker.py  pdfs/alares_3.pdf out/alares_3.marker.md  2-7
# Escaneado (OCR) — 4 páginas, rode inteiro
python run_docling.py pdfs/ot_2_scan.pdf out/ot2.docling.md
python run_marker.py  pdfs/ot_2_scan.pdf out/ot2.marker.md
```

### Regenerar o fixture sintético e pontuar
```bash
cd fixtures && python ../gen_pdf.py    # gera df_sintetica.pdf + groundtruth (roda de dentro de fixtures/)
python score.py outputs/sintetico/df_sintetica.docling.md fixtures/df_sintetica.groundtruth.json
```

## O que comparar
1. **Estrutura da tabela na DF** (`alares_3`): a hierarquia de `cd_conta` deve ficar
   alinhada e os **totais dentro da tabela**.
2. **OCR** (`ot_2_scan`): fidelidade do texto e onde cada parser degrada.
3. **Tempo/página** e tamanho do output.
4. Se houver **GPU**, informe os tempos com GPU e, opcionalmente, rode MinerU (venv separado).

## Arquivos
- `gen_pdf.py` — gera o PDF sintético de DF pt-BR + gabarito JSON.
- `score.py` — pontua um `.md` contra o gabarito (% de valores encontrados).
- `run_docling.py` / `run_marker.py` — runners com faixa de páginas.
- `fixtures/` — PDF sintético + gabarito.
- `outputs/` — saídas já geradas (sintético: 3 parsers; reais: Docling).
