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

### Documentos reais (Docling — baseline medido em CPU)
| Documento | Tipo | Resultado Docling |
|---|---|---|
| `alares_3` (DF CVM, pág 3–8) | digital, tabelas densas | Balanço com **hierarquia de `cd_conta` (1, 1.01, 1.01.01…)** e 3 períodos alinhados; 34,6 s; 1 célula com glitch. Mapeia quase direto para o schema `cd_conta/ds_conta/valor`. |
| `ot_2` (ata, 4 pág) | **escaneado (OCR)** | OCR bom no texto limpo; degrada em carimbos/assinaturas; 83 s. |
| `alares_1` (deck de resultados) | digital, dados em gráficos | narrativa OK; números em gráficos **não saem** (exigem VLM de chart, desligado por padrão em todos os parsers). |

Os `.md` correspondentes estão em `outputs/`.

### Pendência: Marker/MinerU nos documentos REAIS
No ambiente de nuvem (CPU, sem `brew`, releases do GitHub bloqueadas pelo proxy) **não foi
possível** completar Marker/MinerU nos reais:
- **Marker** exige o binário nativo **`llama-server` (llama.cpp)** — o surya 0.22 o spawna
  para inferência de layout/OCR. Sem ele: `SpawnError: llama-server binary not found`.
- **MinerU 4.x** exige um **parse-server VLM** (na prática GPU/vLLM).

Rodar localmente (desktop com o binário instalado, e idealmente GPU) fecha o head-to-head.

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
llama-server --version   # deve responder sem erro
```

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
