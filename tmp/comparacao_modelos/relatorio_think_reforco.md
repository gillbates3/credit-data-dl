# Comparação de modelos — extração de PDFs

- CNPJ: `00000000000000`  |  Modo: `ambos`  |  Modelos: gemini-3.1-flash-lite
- **Critério final = leitura humana das saídas** em `por_modelo/`. As tabelas abaixo apontam onde olhar.

## Trilha qualitativa (markdown)

| Arquivo | Modelo | Modo | Chunks | **Truncados** | Latência (s) | Tok in | Tok out | Tok think | Custo USD | Chars | Nº números |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Relatorio Anual 2025.pdf | gemini-3.1-flash-lite | texto | 10 | 0 | 320.09 | 74561 | 71892 | 15849 | 0.1503 | 182318 | 4974 |
| Relatorio Anual e Demonstracoes Financei | gemini-3.1-flash-lite | texto | 10 | 0 | 371.33 | 70916 | 65045 | 19203 | 0.1441 | 172032 | 4503 |

### Fidelidade numérica (divergência entre modelos, qual)
| Arquivo | Nº A | Nº B | Só em A | Só em B | Em comum |
|---|---:|---:|---:|---:|---:|

## Trilha quantitativa (JSON CVM)

| Arquivo | Modelo | Modo | **Trunc.** | Latência (s) | Tok in | Tok out | Custo USD | Períodos | Contas |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| Relatorio Anual 2025.pdf | gemini-3.1-flash-lite | texto | não | 39.03 | 29337 | 8008 | 0.0277 | 2 | 204 |
| Relatorio Anual e Demonstracoes Financei | gemini-3.1-flash-lite | texto | SIM | 356.51 | 29024 | 2607 | 0.1055 | 0 | 0 |

## Agregado por modelo

| Modelo | Custo USD total | Latência total (s) | Chunks truncados (qual) |
|---|---:|---:|---:|
| gemini-3.1-flash-lite | 0.4276 | 1087.0 | 0 |