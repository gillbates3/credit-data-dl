"""Gera um PDF de demonstrações financeiras pt-BR realista + ground truth JSON.
Formatação típica de DF brasileira: valores em R$ mil, separador de milhar,
negativos entre parênteses, 2 colunas de período, cabeçalhos de seção.
"""
import json
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak)

OUT_PDF = "pdfs/df_sintetica.pdf"
OUT_GT = "pdfs/df_sintetica.groundtruth.json"

def m(v):  # formata número estilo BR (milhar com ponto, negativo entre parênteses)
    s = f"{abs(v):,.0f}".replace(",", ".")
    return f"({s})" if v < 0 else s

styles = getSampleStyleSheet()
h = ParagraphStyle("h", parent=styles["Heading2"], fontSize=12, spaceAfter=6)
sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
normal = styles["Normal"]

# ---- GROUND TRUTH (valores em R$ mil) ----
gt = {
    "empresa": "Companhia Exemplo de Infraestrutura S.A.",
    "moeda": "R$ mil",
    "balanco_patrimonial": {
        "periodos": ["31/12/2024", "31/12/2023"],
        "ativo": {
            "Caixa e equivalentes de caixa": [152340, 98210],
            "Contas a receber de clientes": [421870, 388940],
            "Estoques": [63120, 71050],
            "Tributos a recuperar": [28470, 19980],
            "Total do ativo circulante": [665800, 578180],
            "Imobilizado": [2841500, 2655300],
            "Intangível": [412300, 398100],
            "Investimentos": [88700, 84200],
            "Total do ativo não circulante": [3342500, 3137600],
            "Total do ativo": [4008300, 3715780],
        },
        "passivo": {
            "Fornecedores": [198450, 176320],
            "Empréstimos e financiamentos (circulante)": [345600, 412800],
            "Obrigações trabalhistas e tributárias": [72340, 65110],
            "Total do passivo circulante": [616390, 654230],
            "Empréstimos e financiamentos (não circulante)": [1685400, 1520900],
            "Debêntures": [780000, 780000],
            "Provisões": [64200, 58700],
            "Total do passivo não circulante": [2529600, 2359600],
            "Capital social": [500000, 500000],
            "Reservas de lucros": [362310, 201750],
            "Patrimônio líquido": [862310, 701950],
            "Total do passivo e patrimônio líquido": [4008300, 3715780],
        },
    },
    "dre": {
        "periodos": ["2024", "2023"],
        "contas": {
            "Receita operacional líquida": [3120500, 2814300],
            "Custo dos produtos e serviços vendidos": [-1987400, -1832100],
            "Lucro bruto": [1133100, 982200],
            "Despesas comerciais": [-214300, -198700],
            "Despesas administrativas": [-176800, -165400],
            "Outras receitas (despesas) operacionais": [-42100, 31200],
            "Resultado antes do resultado financeiro (EBIT)": [699900, 649300],
            "Resultado financeiro líquido": [-312700, -288400],
            "Resultado antes dos tributos": [387200, 360900],
            "Imposto de renda e contribuição social": [-131600, -122700],
            "Lucro líquido do exercício": [255600, 238200],
        },
    },
    "indicadores_texto": {
        "EBITDA 2024 (R$ mil)": 934200,
        "Dívida líquida/EBITDA 2024 (x)": 2.86,
        "covenant dívida líquida/EBITDA (máx.)": 3.50,
    },
}

with open(OUT_GT, "w", encoding="utf-8") as f:
    json.dump(gt, f, ensure_ascii=False, indent=2)

def build_table(periodos, rows_dict, bold_rows):
    data = [["", periodos[0], periodos[1]]]
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]
    for i, (label, vals) in enumerate(rows_dict.items(), start=1):
        data.append([label, m(vals[0]), m(vals[1])])
        if label in bold_rows:
            style.append(("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"))
            style.append(("LINEABOVE", (0, i), (-1, i), 0.4, colors.grey))
    t = Table(data, colWidths=[95 * mm, 32 * mm, 32 * mm])
    t.setStyle(TableStyle(style))
    return t

story = []
story.append(Paragraph(gt["empresa"], styles["Title"]))
story.append(Paragraph("Demonstrações Financeiras — Exercício findo em 31 de dezembro de 2024", sub))
story.append(Paragraph("(Valores expressos em milhares de reais — R$ mil, exceto quando indicado)", sub))
story.append(Spacer(1, 8 * mm))

story.append(Paragraph("Balanço Patrimonial — Ativo", h))
bp = gt["balanco_patrimonial"]
story.append(build_table(bp["periodos"], bp["ativo"],
             {"Total do ativo circulante", "Total do ativo não circulante", "Total do ativo"}))
story.append(Spacer(1, 6 * mm))
story.append(Paragraph("Balanço Patrimonial — Passivo e Patrimônio Líquido", h))
story.append(build_table(bp["periodos"], bp["passivo"],
             {"Total do passivo circulante", "Total do passivo não circulante",
              "Patrimônio líquido", "Total do passivo e patrimônio líquido"}))

story.append(PageBreak())
story.append(Paragraph("Demonstração do Resultado do Exercício (DRE)", h))
dre = gt["dre"]
story.append(build_table(dre["periodos"], dre["contas"],
             {"Lucro bruto", "Resultado antes do resultado financeiro (EBIT)",
              "Resultado antes dos tributos", "Lucro líquido do exercício"}))
story.append(Spacer(1, 8 * mm))
story.append(Paragraph("Comentários da Administração (trecho)", h))
story.append(Paragraph(
    "A Companhia encerrou 2024 com EBITDA de R$ 934.200 mil, alta de 9,2% frente a 2023, "
    "refletindo o reajuste tarifário e a diluição de custos fixos. A alavancagem, medida pela "
    "relação dívida líquida/EBITDA, encerrou o exercício em 2,86x, confortavelmente abaixo do "
    "covenant financeiro de 3,50x previsto na escritura da 2ª emissão de debêntures. A administração "
    "reitera o compromisso com a manutenção do rating e com a desalavancagem gradual ao longo de 2025.",
    normal))

doc = SimpleDocTemplate(OUT_PDF, pagesize=A4,
                        leftMargin=18 * mm, rightMargin=18 * mm,
                        topMargin=18 * mm, bottomMargin=18 * mm)
doc.build(story)

# contagem de células numéricas do gabarito (para score)
n_cells = sum(len(v) for v in bp["ativo"].values()) + sum(len(v) for v in bp["passivo"].values()) \
          + sum(len(v) for v in dre["contas"].values())
print(f"PDF gerado: {OUT_PDF}")
print(f"Ground truth: {OUT_GT}")
print(f"Células numéricas no gabarito: {n_cells}")
