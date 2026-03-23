"""
00_setup_estrutura.py
Cria a estrutura de pastas do projeto credit-data-dl.
Execute uma vez antes de qualquer outro script.
"""

import os
from pathlib import Path

# Raiz do projeto — ajuste conforme seu ambiente
PROJETO_RAIZ = Path(__file__).parent.parent


def criar_estrutura():
    pastas = [
        # Landing zone — dados brutos
        "data/01_landing/cvm_raw/dfp",
        "data/01_landing/cvm_raw/itr",
        "data/01_landing/cvm_raw/fre",
        "data/01_landing/anbima",
        "data/01_landing/manual_uploads",
        # Silver — JSONs padronizados por empresa/período
        "data/02_silver",
        # Gold — será populado pelo Supabase (referência local opcional)
        "data/03_gold",
        # Logs de execução
        "logs",
        # Scripts já existem
        "scripts",
    ]

    print(f"Criando estrutura em: {PROJETO_RAIZ}\n")
    for pasta in pastas:
        caminho = PROJETO_RAIZ / pasta
        caminho.mkdir(parents=True, exist_ok=True)
        print(f"  OK  {pasta}")

    print("\nEstrutura criada com sucesso.")
    print("\nPróximos passos:")
    print("  1. Execute: python 01_resolver_codigos_cvm.py")
    print("     → Resolve cod_cvm de todas as empresas e atualiza empresas_abertas.csv")
    print("  2. Execute: python 02_download_cvm.py")
    print("     → Baixa DFP, ITR e FRE para todas as empresas")
    print("  3. Execute: python 03_download_anbima.py")
    print("     → Baixa dados de debêntures da ANBIMA")


if __name__ == "__main__":
    criar_estrutura()
