# credit-data-dl

Pipeline automotizado de extração, tratamento e consolidação de dados financeiros e qualitativos para análise de crédito corporativo (Debêntures).

O projeto adota uma arquitetura baseada na **Semeadura por Tickers**: o usuário informa apenas o código da emissão na B3 (ex: PETR26) e o pipeline "descobre" a empresa emissora, identifica seus dados cadastrais, baixa documentação oficial da CVM de forma inteligente e permite a inclusão de uploads manuais via IA, consolidando tudo em um banco de dados relacional.

---

## ⚙️ Pré-requisitos & Configuração

1. **Dependências em Python:**
```bash
pip install requests playwright supabase python-dotenv pdfplumber google-generativeai
playwright install chromium
```

2. **Supabase & Gemini (Crie o arquivo `.env` na raiz):**
```env
SUPABASE_URL=https://SUA-URL.supabase.co
SUPABASE_KEY=sua_service_role_key
GEMINI_API_KEY=sua_chave_gemini
```
> **Nota:** Use a *service_role key* do Supabase para ter acesso total de gravação, não a *anon key*.

---

## 📂 Estrutura de Pastas

```text
credit-data-dl/
├── emissoes.csv                          ← [INPUT] Debêntures monitoradas (Semente)
├── empresas.csv                          ← [GERADO] Cadastro de empresas e cruzamento CVM
├── .env                                  ← Chaves API (Supabase, Gemini)
├── README.md                             ← Documentação
├── data/
│   ├── 01_landing/                       ← Dados Brutos (Raw)
│   │   ├── anbima/                       ← Dados de mercado brutos
│   │   ├── cvm_raw/                      ← Dados públicos CVM
│   │   └── manual_uploads/{CNPJ}/        ← PDFs fornecidos pelo analista
│   └── 02_silver/{CNPJ}/                 ← Dossiê do Emissor (Consolidado)
│       ├── {CNPJ}.json                   ← Dados Contábeis (CVM + Manual)
│       └── anbima/{TICKER}/              ← Dados de Mercado (Operação)
│           ├── agenda.json
│           ├── caracteristicas.json
│           └── historico_diario.json
└── scripts/
    ├── 01_download_anbima.py             ← [Landing] Baixa dados de mercado
    ├── 02_descobrir_emissores.py         ← [Setup] Sincroniza cadastros
    ├── 03_download_cvm.py                ← [Landing] Baixa dados públicos
    ├── 04_parser_manual_ai.py            ← [Landing] Extrai dados de PDFs (Custo: Tokens)
    ├── 05_consolidacao_silver.py         ← [Silver] Consolida contabilidade no Dossiê
    ├── 06_parser_silver_anbima.py        ← [Silver] Consolida ANBIMA no Dossiê
    ├── 08_upsert_supabase.py             ← [Carga] Injeta o Dossiê completo no Banco
    └── utils_validar_silver.py           ← [QA] Valida integridade do Dossiê
```

---

## 🚀 Como Executar o Pipeline

1. **Coleta de Mercado**
```bash
python scripts/01_download_anbima.py
```

2. **Resolução de Cadastro**
```bash
python scripts/02_descobrir_emissores.py
```

3. **Coleta Pública (CVM)**
```bash
python scripts/03_download_cvm.py --anos 2024
```

4. **Extração IA (Opcional)**
>*Coloque os PDFs em `data/01_landing/manual_uploads/{CNPJ}/`.*
```bash
python scripts/04_parser_manual_ai.py
```

5. **Consolidação do Dossiê (Silver)**
```bash
python scripts/05_consolidacao_silver.py
python scripts/06_parser_silver_anbima.py
```

6. **Validação e Carga**
```bash
python scripts/utils_validar_silver.py
python scripts/08_upsert_supabase.py
```

---

## 🧠 Arquitetura do Dossiê (Silver Layer)

A Camada Silver é o "Dossiê do Emissor". Antes de qualquer dado subir para o banco de dados, ele é organizado em pastas por CNPJ. Isso permite:
1. **Auditoria:** Verificação fácil de quais dados foram extraídos.
2. **Escalabilidade:** Adição de novos tipos de dados (ex: qualitativos) sem quebrar o esquema.
3. **Consistência:** O script de carga (`08`) lê apenas esta pasta, garantindo que o banco reflita exatamente o que foi validado na Silver.
- **Manual como Fallback:** O parser inteligente preenche **lacunas**. O dado manual só entra para anos que a CVM ainda não divulgou ou para emissores puramente fechados que não possuem presença no cadastro de companhias abertas.