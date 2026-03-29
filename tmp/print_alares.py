import json
from pathlib import Path

data = json.loads(Path('data/01_landing/manual_uploads/23438929000100/dados_financeiros.json').read_text(encoding='utf-8'))
periodos = data['periodos']

for periodo, info in sorted(periodos.items()):
    tipo = info['tipo']
    dems = info['demonstracoes']
    print(f"\n{'='*70}")
    print(f"PERIODO: {periodo} ({tipo})")
    print(f"{'='*70}")
    for dem_nome, contas in dems.items():
        print(f"\n  [{dem_nome}]")
        for cd, c in sorted(contas.items(), key=lambda x: x[1].get('ordem', 0)):
            v = c['valor']
            if v is not None:
                v_fmt = f"R$ {v:>18,.0f}"
            else:
                v_fmt = "N/A"
            ds = c['ds_conta'][:55]
            print(f"    {cd:<14} {ds:<55} {v_fmt}")
