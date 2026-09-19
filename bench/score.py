"""Pontua a fidelidade de um markdown extraído contra o ground truth.
Métrica: % de células numéricas do gabarito encontradas no texto (formato BR),
+ tamanho do output + tempo (passado por arg). Simples, objetivo, reproduzível.
"""
import json, re, sys, os

def m(v):
    s = f"{abs(v):,.0f}".replace(",", ".")
    return f"({s})" if v < 0 else s

def all_numbers(gt):
    nums = []
    bp = gt["balanco_patrimonial"]
    for sec in ("ativo", "passivo"):
        for label, vals in bp[sec].items():
            for v in vals:
                nums.append((f"BP/{sec}/{label}", v, m(v)))
    for label, vals in gt["dre"]["contas"].items():
        for v in vals:
            nums.append((f"DRE/{label}", v, m(v)))
    return nums

def score(md_path, gt_path):
    with open(gt_path, encoding="utf-8") as f:
        gt = json.load(f)
    with open(md_path, encoding="utf-8") as f:
        text = f.read()
    # normaliza espaços não-quebra e variações
    norm = text.replace(" ", " ")
    nums = all_numbers(gt)
    found = 0
    missing = []
    for key, v, s in nums:
        # aceita o valor com ou sem parênteses (negativos podem virar -X)
        bare = s.strip("()")
        neg_variants = [s, f"-{bare}", f"({bare})", bare + "-"]
        if v < 0:
            hit = any(variant in norm for variant in neg_variants)
        else:
            hit = s in norm
        if hit:
            found += 1
        else:
            missing.append((key, s))
    total = len(nums)
    return {
        "arquivo_md": os.path.basename(md_path),
        "celulas_gabarito": total,
        "celulas_encontradas": found,
        "fidelidade_pct": round(100 * found / total, 1),
        "tamanho_md_chars": len(text),
        "linhas_tabela_markdown": text.count("|"),
        "faltando_amostra": missing[:8],
    }

if __name__ == "__main__":
    md_path, gt_path = sys.argv[1], sys.argv[2]
    print(json.dumps(score(md_path, gt_path), ensure_ascii=False, indent=2))
