
import requests
import os
import sys
import json
from pathlib import Path

# Carregar do .env.local
PROJETO_RAIZ = Path(__file__).parent.parent
with open(PROJETO_RAIZ / ".env.local") as f:
    env_vars = {}
    for line in f:
        if "=" in line and not line.strip().startswith("#"):
            line = line.strip()
            # Handle possible trailing comments or whitespace
            if "#" in line:
                line = line.split("#")[0].strip()
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()

url = env_vars.get("SUPABASE_URL")
key = env_vars.get("SUPABASE_KEY")

headers = {
    "apikey": key,
    "Authorization": f"Bearer {key}",
    "Accept": "application/json",
    "Range": "0-0"
}

tables = [
    "emissores",
    "demonstracoes_financeiras",
    "deb_caracteristicas",
    "deb_agenda",
    "deb_historico_diario"
]

print("-" * 60)
print(f"VERIFICANDO SCHEMAS NO SUPABASE: {url}")
print("-" * 60)

# O PostgREST expõe a documentação OpenAPI em '/'
print("\nBuscando metadados completos via OpenAPI...")
api_resp = requests.get(f"{url}/rest/v1/", headers=headers)
if api_resp.status_code == 200:
    data = api_resp.json()
    definitions = data.get("definitions", {})
    
    for table in tables:
        print(f"\n- Tabela: {table}")
        if table in definitions:
            properties = definitions[table].get("properties", {})
            cols = list(properties.keys())
            print(f"  Colunas detectadas: {len(cols)}")
            
            novas = [
                "taxa_indicativa", "taxa_compra", "taxa_venda", 
                "duration_dias_uteis", "percentual_pu_par", 
                "referencia_ntnb", "desvio_padrao",
                "percentual_reune", "volume_financeiro", "taxa_media_negocios"
            ]
            for n in novas:
                if n in cols:
                    attr = properties[n]
                    print(f"    ✅ {n} ({attr.get('format', attr.get('type'))})")
                else:
                    if table == "deb_historico_diario":
                        print(f"    ❌ {n}: NÃO ENCONTRADA")
        else:
            print(f"  ❌ Definição não encontrada na API. Verifique as permissões de RLS ou se a tabela existe de fato no schema 'public'.")
else:
    print(f"❌ Não foi possível carregar o OpenAPI: {api_resp.status_code}")

print("\n" + "-" * 60)
