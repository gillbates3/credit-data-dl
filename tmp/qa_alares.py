import pdfplumber
from pathlib import Path

pdf_path = Path("data/01_landing/manual_uploads/23438929000100/Demonstrações Financeiras 4T24.pdf")

with pdfplumber.open(pdf_path) as pdf:
    # Look for pages with financial tables
    with open("tmp_qa_text_alares.txt", "w", encoding="utf-8") as f:
        for i, page in enumerate(pdf.pages):
           # Extract only text that seems like financial tables
           text = page.extract_text()
           if text and any(k in text for k in ["Balanço", "Resultado", "Fluxo", "Caixa", "DRE", "DFC", "BPA", "BPP"]):
               f.write(f"--- PAGE {i+1} ---\n")
               f.write(text + "\n\n")
print("Extraction complete.")
