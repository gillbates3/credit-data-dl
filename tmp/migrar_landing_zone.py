
import json
import os
from pathlib import Path

# Configuração
SCRIPT_DIR = Path(__file__).parent
PROJETO_RAIZ = SCRIPT_DIR.parent
LANDING_ANBIMA = PROJETO_RAIZ / "data" / "01_landing" / "anbima"

# Funções auxiliares copiadas do script 03 (adaptadas)
def f(v):
    if v is None or v == "": return None
    try: return float(str(v).replace(",", "."))
    except (ValueError, TypeError): return None

def i(v):
    if v is None or v == "": return None
    try: return int(float(str(v)))
    except (ValueError, TypeError): return None

def data_curta(v):
    if not v: return None
    return str(v)[:10]

def consolidar_historico(grafico, curva, precos):
    por_data = {}
    def base(data):
        return {
            "data_referencia": data,
            "pu_par": None, "vna": None, "juros": None, "prazo_remanescente": None,
            "pu_indicativo": None, "taxa_indicativa": None, "taxa_compra": None,
            "taxa_venda": None, "duration_dias_uteis": None, "desvio_padrao": None,
            "percentual_pu_par": None, "percentual_vne": None, "intervalo_indicativo_min": None,
            "intervalo_indicativo_max": None, "referencia_ntnb": None, "spread_indicativo": None,
            "volume_financeiro": None, "quantidade_negocios": None, "quantidade_titulos": None,
            "taxa_media_negocios": None, "pu_medio_negocios": None, "reune": None,
            "percentual_reune": None, "pu_indicativo_status": None, "taxa_indicativa_status": None,
            "flag_status": None, "data_ultima_atualizacao": None
        }

    if grafico and isinstance(grafico, dict):
        for p in grafico.get("pus", []):
            d = p.get("data")
            if d:
                r = por_data.setdefault(d, base(d))
                r["pu_par"] = f(p.get("valor_pu_historico"))
                r["pu_indicativo"] = f(p.get("valor_pu_indicativo"))

    if curva and isinstance(curva, dict):
        for p in curva.get("content", []):
            d = p.get("data_referencia")
            if d:
                r = por_data.setdefault(d, base(d))
                if r["pu_par"] is None: r["pu_par"] = f(p.get("pu_par"))
                r["vna"] = f(p.get("vna"))
                r["juros"] = f(p.get("juros"))
                r["prazo_remanescente"] = i(p.get("prazo_remanescente"))
                r["flag_status"] = p.get("flag_status")
                r["data_ultima_atualizacao"] = data_curta(p.get("data_ultima_atualizacao"))

    if precos and isinstance(precos, dict):
        for p in precos.get("precos", []):
            d = p.get("data_referencia")
            if d:
                r = por_data.setdefault(d, base(d))
                r["taxa_indicativa"] = f(p.get("taxa_indicativa"))
                r["taxa_compra"] = f(p.get("taxa_compra"))
                r["taxa_venda"] = f(p.get("taxa_venda"))
                r["duration_dias_uteis"] = f(p.get("duration"))
                r["percentual_pu_par"] = f(p.get("percentual_pu_par"))
                r["percentual_vne"] = f(p.get("percentual_vne"))
                r["desvio_padrao"] = f(p.get("desvio_padrao"))
                r["reune"] = p.get("reune")
                r["intervalo_indicativo_min"] = f(p.get("intervalo_indicativo_minimo"))
                r["intervalo_indicativo_max"] = f(p.get("intervalo_indicativo_maximo"))
                r["referencia_ntnb"] = p.get("data_referencia_ntnb")
                r["pu_indicativo_status"] = p.get("pu_indicativo_status")
                r["taxa_indicativa_status"] = p.get("taxa_indicativa_status")
                r["percentual_reune"] = f(p.get("percentual_reune"))
                if r["data_ultima_atualizacao"] is None:
                    r["data_ultima_atualizacao"] = data_curta(p.get("data_ultima_atualizacao"))
                if r["pu_indicativo"] is None:
                    r["pu_indicativo"] = f(p.get("pu_indicativo"))

    return list(por_data.values())

def carregar_json(p):
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def main():
    print("Iniciando conversão da Landing Zone Anbima...")
    for ticker_dir in LANDING_ANBIMA.iterdir():
        if ticker_dir.is_dir():
            ticker = ticker_dir.name
            print(f"Processando {ticker}...")
            
            p_grafico = ticker_dir / "grafico_pu.json"
            p_curva = ticker_dir / "pu_historico.json"
            p_precos = ticker_dir / "precos.json"
            
            grafico = carregar_json(p_grafico)
            curva = carregar_json(p_curva)
            precos = carregar_json(p_precos)
            
            historico = consolidar_historico(grafico, curva, precos)
            
            if historico:
                with open(ticker_dir / "historico_diario.json", "w", encoding="utf-8") as f_out:
                    json.dump(historico, f_out, indent=2, ensure_ascii=False)
                print(f"  ✅ historico_diario.json criado ({len(historico)} registros).")
                
                # Deletar arquivos antigos
                for p in [p_grafico, p_curva, p_precos]:
                    if p.exists():
                        p.unlink()
                        print(f"  🗑️  {p.name} deletado.")
            else:
                print(f"  ⚠️  Nenhum dado histórico encontrado para consolidar.")

if __name__ == "__main__":
    main()
