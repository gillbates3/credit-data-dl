"""
01_resolver_codigos_cvm.py

Consulta o cadastro público da CVM para resolver cod_cvm de todas
as empresas em empresas_abertas.csv que ainda não têm esse campo preenchido.
Atualiza o CSV com os dados encontrados.

Fonte: https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv
"""

import csv
import io
import re
import time
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
EMPRESAS_CSV = SCRIPT_DIR / "empresas_abertas.csv"
CVM_CAD_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"


def baixar_cadastro_cvm() -> list[dict]:
    """Baixa o cadastro completo de companhias abertas da CVM."""
    print("Baixando cadastro CVM (cad_cia_aberta.csv)...")
    resp = requests.get(CVM_CAD_URL, timeout=60)
    resp.raise_for_status()
    resp.encoding = "latin-1"

    linhas = list(
        csv.DictReader(
            io.StringIO(resp.text),
            delimiter=";",
        )
    )
    print(f"  {len(linhas)} companhias carregadas.\n")
    return linhas


def normalizar(texto: str) -> str:
    """Remove acentos, pontuação e passa para minúsculas para comparação fuzzy."""
    import unicodedata
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9 ]", " ", texto.lower())
    return re.sub(r"\s+", " ", texto).strip()


def buscar_por_cnpj(cadastro: list[dict], cnpj: str) -> dict | None:
    cnpj_limpo = re.sub(r"\D", "", cnpj)
    for linha in cadastro:
        cnpj_cvm = re.sub(r"\D", "", linha.get("CNPJ_CIA", ""))
        if cnpj_cvm == cnpj_limpo:
            return linha
    return None


def buscar_por_nome(cadastro: list[dict], nome: str) -> list[dict]:
    """Busca por nome parcial, retorna até 5 candidatos."""
    nome_norm = normalizar(nome)
    palavras = [p for p in nome_norm.split() if len(p) > 3]
    candidatos = []
    for linha in cadastro:
        nome_cvm = normalizar(linha.get("DENOM_SOCIAL", ""))
        score = sum(1 for p in palavras if p in nome_cvm)
        if score >= max(1, len(palavras) - 2):
            candidatos.append((score, linha))
    candidatos.sort(key=lambda x: -x[0])
    return [c[1] for c in candidatos[:5]]


def resolver_empresa(empresa: dict, cadastro: list[dict]) -> dict:
    """Tenta resolver cod_cvm e cnpj para uma empresa. Retorna empresa atualizada."""
    empresa = dict(empresa)
    cod_cvm = empresa.get("cod_cvm", "").strip()
    cnpj = empresa.get("cnpj", "").strip()
    nome = empresa.get("nome", "").strip()

    # Já tem cod_cvm — validar se bate com o cadastro
    if cod_cvm:
        for linha in cadastro:
            if linha.get("CD_CVM", "").strip() == cod_cvm:
                empresa["cod_cvm"] = cod_cvm
                if not cnpj:
                    empresa["cnpj"] = re.sub(r"\D", "", linha.get("CNPJ_CIA", ""))
                empresa["_status"] = "OK (cod_cvm já existia)"
                empresa["_denom_cvm"] = linha.get("DENOM_SOCIAL", "")
                return empresa

    # Tem CNPJ — buscar pelo CNPJ
    if cnpj:
        encontrado = buscar_por_cnpj(cadastro, cnpj)
        if encontrado:
            empresa["cod_cvm"] = encontrado.get("CD_CVM", "").strip()
            empresa["_status"] = "OK (resolvido por CNPJ)"
            empresa["_denom_cvm"] = encontrado.get("DENOM_SOCIAL", "")
            return empresa

    # Sem CNPJ e sem cod_cvm — buscar por nome
    candidatos = buscar_por_nome(cadastro, nome)
    if len(candidatos) == 1:
        empresa["cod_cvm"] = candidatos[0].get("CD_CVM", "").strip()
        empresa["cnpj"] = re.sub(r"\D", "", candidatos[0].get("CNPJ_CIA", ""))
        empresa["_status"] = "OK (resolvido por nome)"
        empresa["_denom_cvm"] = candidatos[0].get("DENOM_SOCIAL", "")
    elif len(candidatos) > 1:
        empresa["_status"] = "AMBÍGUO — revisar manualmente"
        empresa["_candidatos"] = " | ".join(
            f"{c.get('CD_CVM')} - {c.get('DENOM_SOCIAL')}" for c in candidatos
        )
    else:
        empresa["_status"] = "NÃO ENCONTRADO — verificar manualmente"

    return empresa


def main():
    cadastro = baixar_cadastro_cvm()

    with open(EMPRESAS_CSV, encoding="utf-8") as f:
        empresas = list(csv.DictReader(f))

    print("Resolvendo códigos CVM:\n")
    resolvidas = []
    for emp in empresas:
        resultado = resolver_empresa(emp, cadastro)
        resolvidas.append(resultado)

        status = resultado.get("_status", "")
        denom = resultado.get("_denom_cvm", "")
        print(f"  {emp['nome'][:50]:<50}  {status}")
        if denom:
            print(f"    → CVM: {resultado.get('cod_cvm', '')}  |  {denom}")
        if resultado.get("_candidatos"):
            print(f"    → Candidatos: {resultado['_candidatos']}")
        print()

    # Salvar CSV atualizado (sem colunas internas _*)
    campos_saida = [k for k in resolvidas[0].keys() if not k.startswith("_")]
    with open(EMPRESAS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos_saida, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(resolvidas)

    print(f"empresas_abertas.csv atualizado em: {EMPRESAS_CSV}")

    # Resumo
    ok = sum(1 for r in resolvidas if r.get("_status", "").startswith("OK"))
    print(f"\nResumo: {ok}/{len(resolvidas)} empresas com cod_cvm resolvido.")
    pendentes = [r for r in resolvidas if not r.get("_status", "").startswith("OK")]
    if pendentes:
        print("\nPendentes para revisão manual:")
        for p in pendentes:
            print(f"  - {p['nome']}: {p.get('_status', '')}")
            if p.get("_candidatos"):
                print(f"    Candidatos: {p['_candidatos']}")


if __name__ == "__main__":
    main()
