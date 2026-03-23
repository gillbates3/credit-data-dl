# credit-data-dl
## Pipeline de coleta de dados — Fase 1: Landing Zone

### Pré-requisitos

```bash
pip install requests
```

### Estrutura de pastas

```
credit-data-dl/
├── data/
│   ├── 01_landing/
│   │   ├── cvm_raw/
│   │   │   ├── dfp/          ← DFP anuais auditadas (ZIP + CSV filtrado)
│   │   │   │   └── YYYY/
│   │   │   │       ├── dfp_cia_aberta_YYYY.zip
│   │   │   │       └── filtrado/
│   │   │   │           ├── BPA.csv
│   │   │   │           ├── BPP.csv
│   │   │   │           ├── DRE.csv
│   │   │   │           ├── DFC_MD.csv
│   │   │   │           └── DFC_MI.csv
│   │   │   ├── itr/          ← ITR trimestrais (mesma estrutura)
│   │   │   └── fre/          ← FRE formulário de referência
│   │   ├── anbima/
│   │   │   └── {TICKER}/
│   │   │       ├── caracteristicas.json   ← dados cadastrais da emissão
│   │   │       ├── agenda.json            ← fluxo de eventos (paginado completo)
│   │   │       ├── pu_historico.json      ← série de PU par + VNA (paginada completa)
│   │   │       ├── grafico_pu.json        ← série de PU par + indicativo (desde emissão)
│   │   │       └── precos.json            ← taxas, duration, spread (dias recentes)
│   │   └── manual_uploads/   ← PDFs de fechadas, ratings, escrituras
│   ├── 02_silver/            ← JSONs padronizados (próxima fase)
│   └── 03_gold/              ← Supabase PostgreSQL (próxima fase)
├── scripts/
│   ├── empresas_abertas.csv          ← Lista de empresas com cod_cvm
│   ├── 00_setup_estrutura.py
│   ├── 01_resolver_codigos_cvm.py
│   ├── 02_download_cvm.py
│   └── 03_download_anbima.py
└── README.md
```

### Execução — ordem correta

#### 1. Setup (uma vez)
```bash
python scripts/00_setup_estrutura.py
```

#### 2. Resolver códigos CVM
```bash
python scripts/01_resolver_codigos_cvm.py
```
Consulta o cadastro da CVM e preenche `cod_cvm` para empresas que
estão sem esse campo. Atualiza `empresas_abertas.csv` automaticamente.

Verifique o output — algumas empresas podem precisar de revisão manual
(casos ambíguos ou nomes muito diferentes do cadastro CVM).

#### 3. Download CVM — primeira carga histórica
```bash
# Tudo (DFP + ITR + FRE) de 2018 a hoje — pode demorar 15-30 min
python scripts/02_download_cvm.py

# Ou por tipo e/ou ano específico:
python scripts/02_download_cvm.py --tipo dfp
python scripts/02_download_cvm.py --tipo itr --anos 2023 2024
python scripts/02_download_cvm.py --tipo fre --anos 2022 2023 2024
```

#### 4. Download ANBIMA (scraping via Playwright)
```bash
pip install playwright
playwright install chromium
python scripts/03_download_anbima.py
```

#### 5. Parser ANBIMA → Supabase
```bash
python scripts/04b_parser_anbima.py --dry-run   # testa sem salvar
python scripts/04b_parser_anbima.py             # popula operacoes, agenda, pu_historico
```

### Atualização trimestral

Quando um novo ITR for publicado:
```bash
python scripts/02_download_cvm.py --tipo itr --anos 2025
```
O script verifica se o arquivo já existe antes de baixar novamente.

### Empresas monitoradas

| Empresa | CNPJ | Cód. CVM | Tipo |
|---------|------|----------|------|
| Alares Internet Participações | 23.438.929/0001-00 | 02519-4 | Cat. A |
| CASAN | — | — | Cat. A |
| EcoRodovias | — | — | Cat. A |
| Enauta Participações | — | — | Cat. A |
| Iguá Saneamento | 08.159.965/0001-33 | — | Cat. A |
| Arteris | 02.919.555/0001-67 | — | Cat. B |
| Equipav Saneamento | — | — | Cat. B |
| Aegea Saneamento | 08.827.501/0001-58 | 2339-6 | Cat. B |
| CORSAN | — | — | Cat. A |

### Próximas fases

- **Fase 2 — Silver**: parser numérico (CSV → JSON padronizado por CNPJ/período)
- **Fase 3 — Gold**: upsert no Supabase (`demonstracoes_master`)
- **Fase 4 — Qualitativo**: chunking + embedding de PDFs → `doc_chunks` (pgvector)
- **Fase 5 — Skill 1**: geração do `perfil_empresa.md`