import pdfplumber
from pathlib import Path

pdf_path = Path("data/01_landing/manual_uploads/13733490000187/QMCDemonstracoesFinanceiras2024.pdf")

with pdfplumber.open(pdf_path) as pdf:
    with open("tmp_qa_text.txt", "w", encoding="utf-8") as f:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text and ("Demonstrações" in text or "Fluxo" in text or "Caixa" in text or "Balanço" in text or "Resultado" in text):
                f.write(f"--- PAGE {i+1} ---\n")
                f.write(text + "\n\n")
print("Extraction complete.")
