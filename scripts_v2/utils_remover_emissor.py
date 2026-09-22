"""
Utilitario CLI: remove (hard delete) todos os dados de um grupo economico (por CNPJ).

Mecânica de remoção por grupo econômico — base para a aba "Gerenciar Dados" (§8g).
As FKs do schema NAO tem ON DELETE CASCADE; a remocao respeita a ordem filhos->pai
(ver `servico_repositorio.deletar_dados_emissor`).

Uso:
    # Dry-run: só mostra a contagem atual (NAO apaga nada)
    python scripts_v2/utils_remover_emissor.py <CNPJ>

    # Executa a remocao (apaga tudo, inclusive o cadastro do emissor)
    python scripts_v2/utils_remover_emissor.py <CNPJ> --confirmar

    # Executa mantendo o cadastro do emissor (apaga so os dados; util p/ reprocessar)
    python scripts_v2/utils_remover_emissor.py <CNPJ> --confirmar --manter-emissor
"""

import argparse
import json

try:
    from scripts_v2 import servico_repositorio as repo
except ImportError:
    import servico_repositorio as repo


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove dados de um grupo economico (por CNPJ).")
    parser.add_argument("cnpj", help="CNPJ do emissor (grupo economico)")
    parser.add_argument(
        "--confirmar",
        action="store_true",
        help="Executa a remocao. Sem esta flag, apenas mostra a contagem atual (dry-run).",
    )
    parser.add_argument(
        "--manter-emissor",
        action="store_true",
        help="Mantem a linha em `emissores` (apaga so os dados dependentes).",
    )
    args = parser.parse_args()

    cnpj = repo.normaliza_cnpj(args.cnpj)
    print(f"CNPJ alvo: {cnpj}")

    antes = repo.contar_dados_emissor(cnpj)
    print("Contagem ANTES:")
    print(json.dumps(antes, ensure_ascii=False, indent=2))

    if not args.confirmar:
        print("\n[dry-run] Nada foi removido. Rode com --confirmar para executar.")
        return

    removidos = repo.deletar_dados_emissor(cnpj, incluir_emissor=not args.manter_emissor)
    print("\nLinhas REMOVIDAS:")
    print(json.dumps(removidos, ensure_ascii=False, indent=2))

    depois = repo.contar_dados_emissor(cnpj)
    print("\nContagem DEPOIS:")
    print(json.dumps(depois, ensure_ascii=False, indent=2))

    total_restante = sum(v for k, v in depois.items() if k != "emissores" or not args.manter_emissor)
    if args.manter_emissor:
        total_restante = sum(v for k, v in depois.items() if k != "emissores")
    print(f"\nTotal de linhas de dados restantes: {total_restante}")


if __name__ == "__main__":
    main()
