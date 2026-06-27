# Comparação de modelos — extração de PDFs

- CNPJ: `00000000000000`  |  Modo: `ambos`  |  Modelos: gemini-2.5-flash, gemini-3.1-flash-lite
- **Critério final = leitura humana das saídas** em `por_modelo/`. As tabelas abaixo apontam onde olhar.

## Trilha qualitativa (markdown)

| Arquivo | Modelo | Modo | Chunks | **Truncados** | Latência (s) | Tok in | Tok out | Tok think | Custo USD | Chars | Nº números |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Relatorio Anual 2025.pdf | gemini-2.5-flash | texto | 10 | 0 | 345.12 | 73061 | 88570 | 0 | 0.2433 | 244054 | 5172 |
| Relatorio Anual 2025.pdf | gemini-3.1-flash-lite | texto | 10 | 0 | 130.56 | 73061 | 21244 | 0 | 0.0501 | 47753 | 1707 |
| Relatorio Anual e Demonstracoes Financei | gemini-2.5-flash | texto | 10 | 0 | 184.65 | 42060 | 48935 | 0 | 0.1350 | 129396 | 3327 |
| Relatorio Anual e Demonstracoes Financei | gemini-3.1-flash-lite | texto | 10 | 0 | 97.6 | 69416 | 19930 | 0 | 0.0472 | 43346 | 1710 |

### Fidelidade numérica (divergência entre modelos, qual)
| Arquivo | Nº A | Nº B | Só em A | Só em B | Em comum |
|---|---:|---:|---:|---:|---:|
| Relatorio Anual 2025.pdf | 1527 | 688 | 851 | 12 | 676 |
| Relatorio Anual e Demonstracoes Financei | 982 | 677 | 485 | 180 | 497 |

## Trilha quantitativa (JSON CVM)

| Arquivo | Modelo | Modo | **Trunc.** | Latência (s) | Tok in | Tok out | Custo USD | Períodos | Contas |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| Relatorio Anual 2025.pdf | gemini-2.5-flash | texto | não | 50.89 | 29289 | 12917 | 0.0411 | 2 | 218 |
| Relatorio Anual 2025.pdf | gemini-3.1-flash-lite | texto | não | 17.26 | 29289 | 3561 | 0.0127 | 2 | 80 |
| Relatorio Anual e Demonstracoes Financei | gemini-2.5-flash | texto | não | 0.0 | 0 | 0 | 0.0000 | 0 | 0 |
| Relatorio Anual e Demonstracoes Financei | gemini-3.1-flash-lite | texto | não | 8.96 | 28976 | 1803 | 0.0099 | 2 | 38 |

## Agregado por modelo

| Modelo | Custo USD total | Latência total (s) | Chunks truncados (qual) |
|---|---:|---:|---:|
| gemini-2.5-flash | 0.4194 | 580.7 | 0 |
| gemini-3.1-flash-lite | 0.1200 | 254.4 | 0 |