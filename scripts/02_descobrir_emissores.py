"""
01_resolver_codigos_cvm.py

1. Descoberta: Escaneia a pasta da ANBIMA para encontrar novos emissores (CNPJs).
2. Resolução: Consulta o cadastro público da CVM para resolver cod_cvm.
3. Inteligência: Se houver múltiplos códigos CVM para o mesmo CNPJ, prioriza o registro ATIVO.
4. Sincronização: Atualiza o empresas.csv com todos os dados consolidados.
"""

import csv
import json
import io
import re
from pathlib import Path
import requests

# ── Configuração ─────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
EMPRESAS_CSV = PROJETO_RAIZ / "empresas.csv"
EMISSOES_CSV = PROJETO_RAIZ / "emissoes.csv"
LANDING_ANBIMA = PROJETO_RAIZ / "data" / "01_landing" / "anbima"
CVM_CAD_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"

# ── Helpers ───────────────────────────────────────────────────────────────────

def normaliza_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj)

def carregar_csv_empresas() -> list[dict]:
    if not EMPRESAS_CSV.exists():
        return []
    with open(EMPRESAS_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def baixar_cadastro_cvm() -> list[dict]:
    """Baixa o cadastro completo de companhias abertas da CVM."""
    print(f"Baixando cadastro CVM...")
    try:
        resp = requests.get(CVM_CAD_URL, timeout=60)
        resp.raise_for_status()
        resp.encoding = "latin-1"
        linhas = list(csv.DictReader(io.StringIO(resp.text), delimiter=";"))
        print(f"  {len(linhas)} companhias carregadas.\n")
        return linhas
    except Exception as e:
        print(f"  ERRO ao baixar cadastro CVM: {e}")
        return []

# ── Inteligência de Descoberta (ANBIMA) ───────────────────────────────────────

def escaneia_emissores_anbima() -> dict[str, str]:
    """Escaneia o que foi baixado da ANBIMA e retorna mapa {cnpj: nome}."""
    print("Escaneando dados ANBIMA para novos emissores...")
    emissores_descobertos = {}
    
    if not LANDING_ANBIMA.exists():
        print("  Pasta ANBIMA não encontrada. Execute 03_download_anbima.py primeiro.")
        return {}

    for folder in LANDING_ANBIMA.iterdir():
        if folder.is_dir():
            json_path = folder / "caracteristicas.json"
            if json_path.exists():
                try:
                    with open(json_path, encoding="utf-8") as f:
                        dados = json.load(f)
                        emissor = dados.get("emissao", {}).get("emissor", {})
                        cnpj = normaliza_cnpj(emissor.get("cnpj", ""))
                        nome = emissor.get("nome", "").strip()
                        if cnpj and nome:
                            emissores_descobertos[cnpj] = nome
                except Exception:
                    continue
    
    print(f"  {len(emissores_descobertos)} emissores encontrados na pasta ANBIMA.")
    return emissores_descobertos

def sincronizar_cnpjs_emissoes():
    """Popula os CNPJs faltantes em emissoes.csv consultando a landing zone da ANBIMA."""
    print("Sincronizando CNPJs faltantes em emissoes.csv...")
    if not EMISSOES_CSV.exists():
        print(f"  ERRO: {EMISSOES_CSV.name} não encontrado.")
        return

    # Lê as emissões
    emissions = []
    with open(EMISSOES_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        emissions = list(reader)

    updated = 0
    for row in emissions:
        ticker = row.get("ticker", "").strip()
        # Limpa o CNPJ atual para verificar se está vazio
        current_cnpj = normaliza_cnpj(row.get("cnpj_emissor", ""))
        
        if not current_cnpj and ticker:
            json_path = LANDING_ANBIMA / ticker / "caracteristicas.json"
            if json_path.exists():
                try:
                    with open(json_path, encoding="utf-8") as f:
                        dados = json.load(f)
                        cnpj = normaliza_cnpj(dados.get("emissao", {}).get("emissor", {}).get("cnpj", ""))
                        if cnpj:
                            row["cnpj_emissor"] = cnpj
                            updated += 1
                except Exception as e:
                    print(f"  ERRO ao ler JSON de {ticker}: {e}")

    if updated > 0:
        with open(EMISSOES_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(emissions)
        print(f"  {updated} CNPJs sincronizados em {EMISSOES_CSV.name}.")
    else:
        print("  Nenhum CNPJ novo para sincronizar em emissoes.csv.")

# ── Inteligência de Resolução (CVM) ───────────────────────────────────────────

def buscar_cvm_inteligente(cadastro: list[dict], cnpj: str) -> dict | None:
    """Busca cod_cvm para um CNPJ, priorizando registros ativos."""
    cnpj_alvo = normaliza_cnpj(cnpj)
    candidatos = []
    
    for linha in cadastro:
        if normaliza_cnpj(linha.get("CNPJ_CIA", "")) == cnpj_alvo:
            candidatos.append(linha)
            
    if not candidatos:
        return None
    
    # Se só tem um, retorna ele
    if len(candidatos) == 1:
        return candidatos[0]
    
    # Se tem vários, prioriza SIT = "FASE OPERACIONAL" ou que não tenha "CANCELADA"
    print(f"    AVISO: Múltiplos registros CVM para CNPJ {cnpj}")
    for c in candidatos:
        sit = str(c.get("SIT", "")).upper()
        print(f"      - CVM {c.get('CD_CVM')}: {sit}")
        if "OPERACIONAL" in sit or "ATIVO" in sit:
            return c
            
    # Fallback: retorna o primeiro (ou o último por data de registro se disponível)
    return candidatos[0]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("  credit-data-dl — Resolver CVM & Descoberta")
    print("=" * 60)

    # 1. Carrega o que já temos
    empresas_atuais = carregar_csv_empresas()
    mapa_empresas = {normaliza_cnpj(e["cnpj"]): e for e in empresas_atuais if e.get("cnpj")}
    
    # 1.1 Sincroniza CNPJs de emissões
    sincronizar_cnpjs_emissoes()
    
    # 2. Descoberta ANBIMA
    descobertas = escaneia_emissores_anbima()
    for cnpj, nome in descobertas.items():
        if cnpj not in mapa_empresas:
            print(f"  [NOVO] Descoberto via ANBIMA: {nome} ({cnpj})")
            mapa_empresas[cnpj] = {
                "nome": nome,
                "cnpj": cnpj,
                "cod_cvm": "",
                "tipo_capital": "Fechado", # Default até provar o contrário
                "ticker_acao": "",
                "categoria": "",
                "observacao": "Descoberto via ANBIMA"
            }

    # 3. Baixa CVM
    cadastro_cvm = baixar_cadastro_cvm()
    
    # 4. Resolve e Atualiza
    print("Resolvendo códigos CVM...")
    for cnpj, empresa in mapa_empresas.items():
        # Só tenta resolver se não tiver cod_cvm ou se estiver marcado como fechado (para revalidar)
        if not empresa.get("cod_cvm"):
            resultado = buscar_cvm_inteligente(cadastro_cvm, cnpj)
            if resultado:
                empresa["cod_cvm"] = str(resultado.get("CD_CVM", "")).strip()
                empresa["tipo_capital"] = "Aberto"
                empresa["categoria"] = resultado.get("CATEG_REG", "")
                print(f"  OK: {empresa['nome'][:40]:<40} → CVM {empresa['cod_cvm']}")
            else:
                empresa["tipo_capital"] = "Fechado"
                
    # 5. Salva CSV Final
    # Garante cabeçalho padrão
    fieldnames = ["nome", "cnpj", "cod_cvm", "tipo_capital", "ticker_acao", "categoria", "observacao"]
    with open(EMPRESAS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for emp in sorted(mapa_empresas.values(), key=lambda x: x["nome"]):
            writer.writerow(emp)

    print(f"\nConcluído! {EMPRESAS_CSV.name} atualizado.")
    print(f"Próximo passo: python 03_download_cvm.py")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    main()
