"""
05_validar_silver.py

Valida os JSONs da camada Silver e imprime um relatório de cobertura:
- Quantos períodos por empresa
- Quais demonstrações estão presentes em cada período
- Checagem básica de consistência contábil (Ativo = Passivo + PL)
- Identifica gaps (trimestres faltando)

Uso:
  python 05_validar_silver.py
  python 05_validar_silver.py --cnpj 23438929000100
  python 05_validar_silver.py --mostrar-contas 23438929000100   # lista contas de uma empresa
"""

import argparse
import json
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
SILVER       = PROJETO_RAIZ / "data" / "02_silver"


def carregar_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def buscar_valor(dem: dict, prefixo: str) -> float | None:
    """Busca o valor de uma conta pelo prefixo do cd_conta."""
    for cd, conta in dem.items():
        if cd == prefixo or cd.startswith(prefixo + "."):
            if cd == prefixo:
                return conta.get("valor")
    return None


def checar_balanco(periodo_dados: dict) -> tuple[bool, str]:
    """Verifica se Ativo ≈ Passivo + PL."""
    dem = periodo_dados.get("demonstracoes", {})
    bpa = dem.get("BPA", {})
    bpp = dem.get("BPP", {})

    ativo = buscar_valor(bpa, "1")
    passivo_pl = buscar_valor(bpp, "2")

    if ativo is None or passivo_pl is None:
        return None, "dados insuficientes"

    diferenca = abs(ativo - passivo_pl)
    tolerancia = abs(ativo) * 0.001  # 0.1%

    if diferenca <= tolerancia:
        return True, f"OK  Ativo={ativo:,.0f}  P+PL={passivo_pl:,.0f}"
    else:
        return False, f"DIVERGE  Ativo={ativo:,.0f}  P+PL={passivo_pl:,.0f}  Diff={diferenca:,.0f}"


def detectar_gaps(periodos: list[str]) -> list[str]:
    """Identifica anos sem nenhum período."""
    if not periodos:
        return []
    anos = sorted({p[:4] for p in periodos})
    ano_min, ano_max = int(anos[0]), int(anos[-1])
    faltando = [str(a) for a in range(ano_min, ano_max + 1) if str(a) not in anos]
    return faltando


def relatorio_empresa(dados: dict, mostrar_contas: bool = False):
    nome = dados.get("nome", "?")
    cnpj = dados.get("cnpj", "?")
    cod_cvm = dados.get("cod_cvm", "?")
    periodos = dados.get("periodos", {})

    print(f"\n{'─'*60}")
    print(f"  {nome}")
    print(f"  CNPJ: {cnpj}  |  CVM: {cod_cvm}")
    print(f"  Períodos encontrados: {len(periodos)}")

    if not periodos:
        print("  AVISO: sem dados — verificar cod_cvm e CSVs filtrados")
        return

    lista_periodos = sorted(periodos.keys())
    print(f"  Intervalo: {lista_periodos[0]} → {lista_periodos[-1]}")

    gaps = detectar_gaps(lista_periodos)
    if gaps:
        print(f"  GAPS (anos sem dados): {', '.join(gaps)}")

    print()
    print(f"  {'Período':<14} {'Tipo':<5} {'Demonstrações':<30} {'Balanço'}")
    print(f"  {'─'*14} {'─'*5} {'─'*30} {'─'*30}")

    for periodo in sorted(periodos.keys(), reverse=True):
        p = periodos[periodo]
        tipo = p.get("tipo", "?")
        dems = sorted(p.get("demonstracoes", {}).keys())
        ok, msg = checar_balanco(p)
        ok_str = "✓" if ok is True else ("?" if ok is None else "✗")
        print(f"  {periodo:<14} {tipo:<5} {', '.join(dems):<30} {ok_str} {msg}")

    if mostrar_contas:
        print(f"\n  Contas disponíveis (primeiro período):")
        primeiro = sorted(periodos.keys())[-1]
        p = periodos[primeiro]
        for dem_nome, contas in sorted(p.get("demonstracoes", {}).items()):
            print(f"\n    [{dem_nome}]")
            for cd, conta in sorted(contas.items()):
                print(f"      {cd:<12} {conta['ds_conta'][:50]:<50}  {conta['valor']:>15,.2f}")


def main():
    parser = argparse.ArgumentParser(
        description="Valida JSONs da camada Silver."
    )
    parser.add_argument("--cnpj", help="Validar só esta empresa")
    parser.add_argument(
        "--mostrar-contas",
        action="store_true",
        help="Lista todas as contas do primeiro período",
    )
    args = parser.parse_args()

    # Busca todos os JSONs que têm o mesmo nome da pasta pai (o CNPJ)
    jsons = []
    for p in SILVER.iterdir():
        if p.is_dir():
            cnpj_json = p / f"{p.name}.json"
            if cnpj_json.exists():
                jsons.append(cnpj_json)
    
    jsons = sorted(jsons)

    if not jsons:
        print(f"Nenhum JSON de CNPJ encontrado em {SILVER}")
        print("Execute scripts/05_consolidacao_silver.py primeiro.")
        return

    if args.cnpj:
        cnpj_limpo = "".join(c for c in args.cnpj if c.isdigit())
        jsons = [j for j in jsons if j.stem == cnpj_limpo]
        if not jsons:
            print(f"JSON para CNPJ {args.cnpj} não encontrado em {SILVER}/{cnpj_limpo}/")
            return

    print(f"\n{'='*60}")
    print("  credit-data-dl — Validação Silver")
    print(f"{'='*60}")
    print(f"  {len(jsons)} empresa(s) para validar\n")

    total_periodos = 0
    erros_balanco = 0

    for json_path in jsons:
        dados = carregar_json(json_path)
        relatorio_empresa(dados, mostrar_contas=args.mostrar_contas)

        n = len(dados.get("periodos", {}))
        total_periodos += n

        for p in dados.get("periodos", {}).values():
            ok, _ = checar_balanco(p)
            if ok is False:
                erros_balanco += 1

    print(f"\n{'='*60}")
    print(f"  Total de períodos processados: {total_periodos}")
    if erros_balanco:
        print(f"  Divergências de balanço:       {erros_balanco}")
    else:
        print(f"  Balanços: todos consistentes")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
